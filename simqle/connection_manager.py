"""Defines the ConnectionManager and Connection Classes."""


from yaml import safe_load
from sqlalchemy import create_engine
from sqlalchemy.sql import text, bindparam
from sqlalchemy.types import VARCHAR
from urllib.parse import quote_plus
from simqle.constants import DEFAULT_FILE_LOCATIONS


class ConnectionManager:
    """
    The Connection Manager Class.

    Create an instance of this class with a yaml configuration file. If no
    yaml file is given, the first connection file found in default locations
    will be used instead.

    This is the class from which you execute sql and return recordsets, using
    the public methods self.execute_sql and self.recordset.
    """

    def __init__(self, file_name=None):
        """
        Initialise a ConnectionManager.

        Connections are loaded lazily as required, only the config is loaded
        on initialisation.
        """
        self.connections = {}

        if not file_name:
            # file_name isn't given so we search through the possible default
            # file locations, which are in order of priority.

            for default_file_name in DEFAULT_FILE_LOCATIONS:
                try:
                    self.config = self._load_yaml_file(default_file_name)
                except:  # noqa TODO: add file not found specific exception.
                    continue

            raise Exception("No file_name is specified and no files in "
                            "default locations are found.")

        else:
            self.config = self._load_yaml_file(file_name)

    # --- Public Methods: ---

    def recordset(self, con_name, sql, params=None):
        """Return recordset from connection."""
        connection = self._get_connection(con_name)
        return connection.recordset(con_name, sql, params=None)

    def execute_sql(self, con_name, sql, params=None):
        """Execute SQL on a given connection."""
        connection = self._get_connection(con_name)
        return connection.execute_sql(con_name, sql, params=None)

    def get_engine(self, con_name):
        """Return the engine of a Connection by it's name."""
        return self._get_connection(con_name).engine()

    def get_connection(self, con_name):
        """
        Return the engine of a Connection by it's name.

        Deprecated, only exists for backwards compatibility.
        """
        return self.get_engine()  # TODO: add warning

    # --- Private Methods: ---

    def _load_yaml_file(self, connections_file):
        """Load the configuration from the given file."""
        with open(connections_file) as file:
            return safe_load(file.read())

    def _get_connection(self, conn_name):
        """
        Return a connection object from its name.

        Connection objects are created and saved the first time they are
        called.
        """
        # Return already initialised connection if it exists.
        if conn_name in self.connections:
            return self.connections[conn_name]

        # A new Connection instance is required.
        for conn_config in self.config["connections"]:
            if conn_config["name"] == conn_name:
                self.connections[conn_name] = _Connection(conn_config)
                return self.connections[conn_name]

        raise Exception(f"Unknown connection {conn_name}")


class _Connection:
    """
    The _Connection class.

    This represents a single connection. This class also managers the execution
    of SQL, including the management of transactions.

    The engine is lazily loaded the first time either execute_sql or recordset
    is called.

    This class shouldn't be loaded outside the ConnectionManager class, and so
    is marked as internal only.
    """

    def __init__(self, conn_config):
        """Create a new Connection from a config dict."""
        self.driver = conn_config['driver']
        self._engine = None

        # Edit the connection based on configuration options.

        # for Microsoft ODBC connections, for example, the connection string
        # must be url escaped. We do this for the user if the url_escape
        # option is True. See here for example and more info:
        # https://docs.sqlalchemy.org/en/13/dialects/mssql.html
        #   #pass-through-exact-pyodbc-string
        if 'url_escape' in conn_config:
            self.connection_string = quote_plus(conn_config['connection'])
        else:
            self.connection_string = conn_config['connection']

    def _connect(self):
        """Create an engine based on sqlalchemy's create_engine."""
        self.engine = create_engine(self.driver + self.connection_string)

    @property
    def engine(self):
        """Load the engine if it hasn't been loaded before."""
        if not self._engine:
            self._connect()

        return self._engine

    def _execute_sql(self, sql, params=None):
        """Execute :sql: on this connection with named :params:."""
        bound_sql = _Connection._bind_sql(sql, params)

        # TODO: discuss whether a connection should be closed on each
        # transaction.
        connection = self.engine.connect()
        transaction = connection.begin()

        # execute the query, and rollback on error
        try:
            connection.execute(bound_sql)
            transaction.commit()

        except Exception as exception:
            transaction.rollback()
            raise exception

        finally:
            connection.close()

    def _recordset(self, sql, params=None):
        """
        Execute <sql> on <con>, with named <params>.

        Return (data, headings)
        """
        # bind the named parameters.
        bound_sql = self._bind_sql(sql, params)

        # start the connection.
        connection = self.engine.connect()
        transaction = connection.begin()

        # get the results from the query.
        result = connection.execute(bound_sql)
        data = result.fetchall()
        headings = result.keys()

        # commit and close the connection
        transaction.commit()
        connection.close()

        return data, headings

    @staticmethod
    def _bind_sql(sql, params):
        bound_sql = text(sql)  # convert to the useful sqlalchemy text

        if params:  # add the named parameters
            bound_sql = _Connection._bind_params(bound_sql, params)

        return bound_sql

    @staticmethod
    def _bind_params(bound_sql, params):
        """Bind named parameters to the given sql."""
        for key, value in params.items():
            if isinstance(value, str):
                bound_sql = bound_sql.bindparams(
                    bindparam(key=key, value=value, type_=VARCHAR(None))
                )
            else:
                bound_sql = bound_sql.bindparams(
                    bindparam(key=key, value=value)
                )
        return bound_sql