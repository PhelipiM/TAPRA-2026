import base64
import json
import logging
import os
from datetime import date, datetime, timezone
from decimal import Decimal

import pyodbc
import requests
import azure.functions as func
from azure.storage.filedatalake import DataLakeServiceClient

app = func.FunctionApp()

def _upload_cursor_results(cursor, table_name: str, entity_name: str) -> int:
    columns = [column[0] for column in cursor.description]
    rows = cursor.fetchall()
    records = [dict(zip(columns, row)) for row in rows]

    def json_default(value):
        if isinstance(value, (date, datetime)):
            return value.isoformat()
        if isinstance(value, Decimal):
            return str(value)
        if isinstance(value, bytes):
            return base64.b64encode(value).decode("ascii")
        return str(value)

    now = datetime.now(timezone.utc)
    file_name = f"{entity_name}_{now:%Y%m%dT%H%M%SZ}.json"
    file_path = (
        f"itsm/{entity_name}/ano={now:%Y}/mes={now:%m}/dia={now:%d}/{file_name}"
    )
    connection_string = os.getenv("DATALAKE_CONNECTION_STRING")
    if not connection_string:
        raise ValueError("A configuração DATALAKE_CONNECTION_STRING não foi definida.")

    payload = json.dumps(
        records, ensure_ascii=False, default=json_default
    ).encode("utf-8")

    datalake = DataLakeServiceClient.from_connection_string(connection_string)
    try:
        file_client = datalake.get_file_system_client("bronze").get_file_client(
            file_path
        )
        file_client.upload_data(payload, overwrite=True)
    finally:
        datalake.close()

    logging.info(
        "Exportada itsm.%s: %s linhas para bronze/%s",
        table_name,
        len(rows),
        file_path,
    )
    return len(rows)


_BRONZE_ENTITIES = (
    ("chamados", "chamado"),
    ("analistas", "analista"),
    ("categorias", "categoria"),
    ("chamados_sla", "chamado_sla"),
    ("chamados_status_historico", "chamado_status_historico"),
    ("clientes_organizacao", "cliente_organizacao"),
    ("csat_avaliacoes", "csat_avaliacao"),
    ("filas", "fila"),
    ("slas", "sla"),
    ("solicitantes", "solicitante"),
)


def _required_setting(name: str) -> str:
    value = os.getenv(name)
    if not value:
        raise ValueError(f"A configuração {name} não foi definida.")
    return value


def _read_latest_bronze_snapshots() -> dict[str, list[dict]]:
    connection_string = _required_setting("DATALAKE_CONNECTION_STRING")
    datalake = DataLakeServiceClient.from_connection_string(connection_string)
    snapshots = {}
    try:
        file_system = datalake.get_file_system_client("bronze")
        for entity_name, table_name in _BRONZE_ENTITIES:
            folder = f"itsm/{entity_name}"
            candidates = [
                path.name
                for path in file_system.get_paths(path=folder)
                if not path.is_directory
                and path.name.endswith(".json")
                and path.name.rsplit("/", 1)[-1].startswith(f"{entity_name}_")
            ]
            if not candidates:
                raise FileNotFoundError(
                    f"Nenhum snapshot JSON encontrado em bronze/{folder}."
                )

            latest_path = max(candidates)
            content = file_system.get_file_client(latest_path).download_file().readall()
            records = json.loads(content)
            if not isinstance(records, list) or any(
                not isinstance(record, dict) for record in records
            ):
                raise ValueError(f"Snapshot inválido para itsm.{table_name}.")
            snapshots[table_name] = records
            logging.info(
                "Snapshot selecionado para itsm.%s: bronze/%s (%s linhas)",
                table_name,
                latest_path,
                len(records),
            )
    finally:
        datalake.close()
    return snapshots


def _destination_connection_string() -> str:
    host = _required_setting("TARGET_SQL_HOST")
    database = _required_setting("TARGET_SQL_DATABASE")
    user = _required_setting("TARGET_SQL_USER")
    password = _required_setting("TARGET_SQL_PASSWORD")

    def quoted(value: str) -> str:
        return "{" + value.replace("}", "}}") + "}"

    return (
        "DRIVER={ODBC Driver 18 for SQL Server};"
        f"SERVER=tcp:{host},1433;"
        f"DATABASE={quoted(database)};"
        f"UID={quoted(user)};"
        f"PWD={quoted(password)};"
        "Encrypt=yes;TrustServerCertificate=no;Connection Timeout=30;"
    )


def _destination_table_order(cursor, table_names: list[str]) -> tuple[list[str], dict]:
    placeholders = ",".join("?" for _ in table_names)
    cursor.execute(
        f"""
        SELECT t.name, c.name, ty.name, c.is_identity, c.is_computed,
               COALESCE(pk.key_ordinal, 0)
        FROM sys.tables AS t
        JOIN sys.schemas AS s ON s.schema_id = t.schema_id
        JOIN sys.columns AS c ON c.object_id = t.object_id
        JOIN sys.types AS ty ON ty.user_type_id = c.user_type_id
        LEFT JOIN (
            SELECT ic.object_id, ic.column_id, ic.key_ordinal
            FROM sys.indexes AS ix
            JOIN sys.index_columns AS ic ON ic.object_id = ix.object_id
                AND ic.index_id = ix.index_id
            WHERE ix.is_primary_key = 1
        ) AS pk ON pk.object_id = c.object_id AND pk.column_id = c.column_id
        WHERE s.name = ? AND t.name IN ({placeholders})
        ORDER BY t.name, c.column_id
        """,
        ("itsm", *table_names),
    )

    schema = {}
    for row in cursor.fetchall():
        table_name, column_name, sql_type, is_identity, is_computed, key_ordinal = row
        table = schema.setdefault(
            table_name, {"columns": {}, "primary_key": []}
        )
        table["columns"][column_name] = {
            "type": sql_type.lower(),
            "identity": bool(is_identity),
            "computed": bool(is_computed),
        }
        if key_ordinal:
            table["primary_key"].append((key_ordinal, column_name))

    missing = set(table_names) - set(schema)
    if missing:
        raise ValueError(
            "Tabelas ausentes no destino (schema itsm): " + ", ".join(sorted(missing))
        )
    for table_name, table in schema.items():
        table["primary_key"] = [
            column_name
            for _, column_name in sorted(table["primary_key"])
        ]
        if not table["primary_key"]:
            raise ValueError(f"A tabela itsm.{table_name} não possui chave primária.")

    cursor.execute(
        """
        SELECT OBJECT_SCHEMA_NAME(fk.referenced_object_id),
               OBJECT_NAME(fk.referenced_object_id),
               OBJECT_SCHEMA_NAME(fk.parent_object_id),
               OBJECT_NAME(fk.parent_object_id)
        FROM sys.foreign_keys AS fk
        """
    )
    edges = {
        (parent_table, child_table)
        for parent_schema, parent_table, child_schema, child_table in cursor.fetchall()
        if parent_schema == "itsm"
        and child_schema == "itsm"
        and parent_table in schema
        and child_table in schema
    }

    dependencies = {table_name: set() for table_name in table_names}
    for parent_table, child_table in edges:
        dependencies[child_table].add(parent_table)

    ordered = []
    remaining = {name: set(parents) for name, parents in dependencies.items()}
    while remaining:
        ready = [name for name in table_names if name in remaining and not remaining[name]]
        if not ready:
            raise ValueError(
                "As chaves estrangeiras do destino contêm dependências cíclicas "
                "entre as tabelas a importar."
            )
        for table_name in ready:
            ordered.append(table_name)
            remaining.pop(table_name)
        for parents in remaining.values():
            parents.difference_update(ready)
    return ordered, schema


def _upsert_snapshot(cursor, table_name: str, table_schema: dict, records: list[dict]) -> int:
    def quote_identifier(name: str) -> str:
        return f"[{name.replace(']', ']]')}]"

    qualified_table = f"[itsm].{quote_identifier(table_name)}"
    primary_key = table_schema["primary_key"]
    column_metadata = table_schema["columns"]
    writable_types = {"timestamp", "rowversion"}
    written = 0
    if not records:
        return written

    columns = [
        column_name
        for column_name, metadata in column_metadata.items()
        if not metadata["computed"]
        and metadata["type"] not in writable_types
        and any(column_name in record for record in records)
    ]
    if any(column_name not in columns for column_name in primary_key):
        raise ValueError(f"O snapshot de itsm.{table_name} não contém a chave primária.")
    if not columns:
        raise ValueError(f"Nenhuma coluna compatível encontrada para itsm.{table_name}.")

    key_predicate = " AND ".join(
        f"{quote_identifier(name)} = ?" for name in primary_key
    )
    non_key_columns = [name for name in columns if name not in primary_key]
    insert_columns = ", ".join(quote_identifier(name) for name in columns)
    insert_values = ", ".join("?" for _ in columns)
    if non_key_columns:
        update_columns = ", ".join(
            f"{quote_identifier(name)} = ?" for name in non_key_columns
        )
        statement = (
            f"IF EXISTS (SELECT 1 FROM {qualified_table} WHERE {key_predicate}) "
            f"BEGIN UPDATE {qualified_table} SET {update_columns} "
            f"WHERE {key_predicate} END ELSE "
            f"INSERT INTO {qualified_table} ({insert_columns}) VALUES ({insert_values})"
        )
    else:
        statement = (
            f"IF NOT EXISTS (SELECT 1 FROM {qualified_table} WHERE {key_predicate}) "
            f"INSERT INTO {qualified_table} ({insert_columns}) VALUES ({insert_values})"
        )

    identity_columns = {
        name for name, metadata in column_metadata.items() if metadata["identity"]
    }
    enable_identity = bool(identity_columns.intersection(columns))
    if enable_identity:
        cursor.execute(f"SET IDENTITY_INSERT {qualified_table} ON")
    try:
        for record in records:
            if any(name not in record or record[name] is None for name in primary_key):
                raise ValueError(f"Registro sem chave primária em itsm.{table_name}.")
            values = {}
            for column_name in columns:
                value = record.get(column_name)
                if (
                    value is not None
                    and column_metadata[column_name]["type"] in {"binary", "varbinary", "image"}
                ):
                    value = base64.b64decode(value)
                values[column_name] = value

            key_values = tuple(values[name] for name in primary_key)
            if non_key_columns:
                parameters = (
                    *key_values,
                    *(values[name] for name in non_key_columns),
                    *key_values,
                    *(values[name] for name in columns),
                )
            else:
                parameters = (*key_values, *(values[name] for name in columns))
            cursor.execute(statement, parameters)
            written += 1
    finally:
        if enable_identity:
            cursor.execute(f"SET IDENTITY_INSERT {qualified_table} OFF")
    return written


@app.timer_trigger(
    schedule="0 0 2 * * *", arg_name="myTimer", run_on_startup=False, use_monitor=True
)
def sync_bronze_to_target_db(myTimer: func.TimerRequest) -> None:
    if myTimer.past_due:
        logging.warning("A sincronização diária está atrasada.")

    snapshots = _read_latest_bronze_snapshots()
    connection = pyodbc.connect(_destination_connection_string())
    cursor = connection.cursor()
    try:
        ordered_tables, destination_schema = _destination_table_order(
            cursor, list(snapshots)
        )
        for table_name in ordered_tables:
            try:
                count = _upsert_snapshot(
                    cursor,
                    table_name,
                    destination_schema[table_name],
                    snapshots[table_name],
                )
                connection.commit()
                logging.info(
                    "Sincronizada itsm.%s: %s registros processados",
                    table_name,
                    count,
                )
            except Exception:
                connection.rollback()
                logging.exception("Falha ao sincronizar itsm.%s", table_name)
                raise
    finally:
        cursor.close()
        connection.close()


@app.timer_trigger(
    schedule="0 * * * * *", arg_name="myTimer", run_on_startup=False, use_monitor=False
)

def extract_chamado(myTimer: func.TimerRequest) -> None:
    logging.info('tabela chamado')
    host_sql = os.getenv("HOST")
    database_sql = os.getenv("DATABASE")
    user_sql = os.getenv("USER")
    password_sql = os.getenv("PASSWORD")

    connection_string = (
        "DRIVER={ODBC Driver 18 for SQL Server};"
        f"SERVER=tcp:{host_sql},1433;"
        f"DATABASE={database_sql};"
        f"UID={user_sql};"
        f"PWD={password_sql};"
        "Encrypt=yes;"
        "TrustServerCertificate=no;"
        "Connection Timeout=30;"
    )

    try:
        with pyodbc.connect(connection_string) as connection:
            cursor = connection.cursor()
            cursor.execute("SELECT * FROM itsm.chamado")
            _upload_cursor_results(cursor, "chamado", "chamados")
            cursor.close()
    except Exception:
        logging.exception("Falha ao exportar itsm.chamado")
        raise

@app.timer_trigger(
    schedule="0 * * * * *", arg_name="myTimer", run_on_startup=False, use_monitor=False
)
def extract_analista(myTimer: func.TimerRequest) -> None:

    driver = "{ODBC Driver 18 for SQL Server}"
    host_sql = os.getenv("HOST")
    database_sql = os.getenv("DATABASE")
    user_sql = os.getenv("USER")
    pass_sql = os.getenv("PASSWORD")

    connection_string = (
        f"Driver={driver};"
        f"Server=tcp:{host_sql},1433;"
        f"Database={database_sql};"
        f"Uid={user_sql};"
        f"Pwd={pass_sql};"
        "Encrypt=yes;"
        "TrustServerCertificate=no;"
        "Connection Timeout=30;"
    )

    try:
        conexao = pyodbc.connect(connection_string)
        cursor = conexao.cursor()

        query = "SELECT * FROM itsm.analista"

        cursor.execute(query)

        retorno = _upload_cursor_results(cursor, "analista", "analistas")

        logging.info(retorno)

        cursor.close()
        conexao.close()
        logging.info("conexao fechada")
    except Exception as e:
        print(f"Erro ao conectar: {e}")


@app.timer_trigger(
    schedule="0 * * * * *", arg_name="myTimer", run_on_startup=False, use_monitor=False
)
def extract_categoria(myTimer: func.TimerRequest) -> None:

    driver = "{ODBC Driver 18 for SQL Server}"
    host_sql = os.getenv("HOST")
    database_sql = os.getenv("DATABASE")
    user_sql = os.getenv("USER")
    pass_sql = os.getenv("PASSWORD")

    # string de conexao
    connection_string = (
        f"Driver={driver};"
        f"Server=tcp:{host_sql},1433;"
        f"Database={database_sql};"
        f"Uid={user_sql};"
        f"Pwd={pass_sql};"
        "Encrypt=yes;"
        "TrustServerCertificate=no;"
        "Connection Timeout=30;"
    )

    # tentativa de conexao
    try:
        conexao = pyodbc.connect(connection_string)
        cursor = conexao.cursor()

        query = "SELECT * FROM itsm.categoria"

        cursor.execute(query)

        retorno = _upload_cursor_results(cursor, "categoria", "categorias")

        logging.info(retorno)

        cursor.close()
        conexao.close()
        logging.info("conexao fechada")
    except Exception as e:
        print(f"Erro ao conectar: {e}")


@app.timer_trigger(
    schedule="0 * * * * *", arg_name="myTimer", run_on_startup=False, use_monitor=False
)
def extract_chamado_sla(myTimer: func.TimerRequest) -> None:

    driver = "{ODBC Driver 18 for SQL Server}"
    host_sql = os.getenv("HOST")
    database_sql = os.getenv("DATABASE")
    user_sql = os.getenv("USER")
    pass_sql = os.getenv("PASSWORD")

    # string de conexao
    connection_string = (
        f"Driver={driver};"
        f"Server=tcp:{host_sql},1433;"
        f"Database={database_sql};"
        f"Uid={user_sql};"
        f"Pwd={pass_sql};"
        "Encrypt=yes;"
        "TrustServerCertificate=no;"
        "Connection Timeout=30;"
    )

    # tentativa de conexao
    try:
        conexao = pyodbc.connect(connection_string)
        cursor = conexao.cursor()

        query = "SELECT * FROM itsm.chamado_sla"

        cursor.execute(query)

        retorno = _upload_cursor_results(cursor, "chamado_sla", "chamados_sla")

        logging.info(retorno)

        cursor.close()
        conexao.close()
        logging.info("conexao fechada")
    except Exception as e:
        print(f"Erro ao conectar: {e}")


@app.timer_trigger(
    schedule="0 * * * * *", arg_name="myTimer", run_on_startup=False, use_monitor=False
)
def extract_chamado_status_historico(myTimer: func.TimerRequest) -> None:

    driver = "{ODBC Driver 18 for SQL Server}"
    host_sql = os.getenv("HOST")
    database_sql = os.getenv("DATABASE")
    user_sql = os.getenv("USER")
    pass_sql = os.getenv("PASSWORD")

    # string de conexao
    connection_string = (
        f"Driver={driver};"
        f"Server=tcp:{host_sql},1433;"
        f"Database={database_sql};"
        f"Uid={user_sql};"
        f"Pwd={pass_sql};"
        "Encrypt=yes;"
        "TrustServerCertificate=no;"
        "Connection Timeout=30;"
    )

    # tentativa de conexao
    try:
        conexao = pyodbc.connect(connection_string)
        cursor = conexao.cursor()

        query = "SELECT * FROM itsm.chamado_status_historico"

        cursor.execute(query)

        retorno = _upload_cursor_results(
            cursor, "chamado_status_historico", "chamados_status_historico"
        )

        logging.info(retorno)

        cursor.close()
        conexao.close()
        logging.info("conexao fechada")
    except Exception as e:
        print(f"Erro ao conectar: {e}")


@app.timer_trigger(
    schedule="0 * * * * *", arg_name="myTimer", run_on_startup=False, use_monitor=False
)
def extract_cliente_organizacao(myTimer: func.TimerRequest) -> None:

    driver = "{ODBC Driver 18 for SQL Server}"
    host_sql = os.getenv("HOST")
    database_sql = os.getenv("DATABASE")
    user_sql = os.getenv("USER")
    pass_sql = os.getenv("PASSWORD")

    # string de conexao
    connection_string = (
        f"Driver={driver};"
        f"Server=tcp:{host_sql},1433;"
        f"Database={database_sql};"
        f"Uid={user_sql};"
        f"Pwd={pass_sql};"
        "Encrypt=yes;"
        "TrustServerCertificate=no;"
        "Connection Timeout=30;"
    )

    # tentativa de conexao
    try:
        conexao = pyodbc.connect(connection_string)
        cursor = conexao.cursor()

        query = "SELECT * FROM itsm.cliente_organizacao"

        cursor.execute(query)

        retorno = _upload_cursor_results(
            cursor, "cliente_organizacao", "clientes_organizacao"
        )

        logging.info(retorno)

        cursor.close()
        conexao.close()
        logging.info("conexao fechada")
    except Exception as e:
        print(f"Erro ao conectar: {e}")


@app.timer_trigger(
    schedule="0 * * * * *", arg_name="myTimer", run_on_startup=False, use_monitor=False
)
def extract_csat_avaliacao(myTimer: func.TimerRequest) -> None:

    driver = "{ODBC Driver 18 for SQL Server}"
    host_sql = os.getenv("HOST")
    database_sql = os.getenv("DATABASE")
    user_sql = os.getenv("USER")
    pass_sql = os.getenv("PASSWORD")

    # string de conexao
    connection_string = (
        f"Driver={driver};"
        f"Server=tcp:{host_sql},1433;"
        f"Database={database_sql};"
        f"Uid={user_sql};"
        f"Pwd={pass_sql};"
        "Encrypt=yes;"
        "TrustServerCertificate=no;"
        "Connection Timeout=30;"
    )

    # tentativa de conexao
    try:
        conexao = pyodbc.connect(connection_string)
        cursor = conexao.cursor()

        logging.info("conectado com sucesso negão")

        query = "SELECT * FROM itsm.csat_avaliacao"

        cursor.execute(query)

        retorno = _upload_cursor_results(
            cursor, "csat_avaliacao", "csat_avaliacoes"
        )

        logging.info(retorno)

        cursor.close()
        conexao.close()
        logging.info("conexao fechada")
    except Exception as e:
        print(f"Erro ao conectar: {e}")


@app.timer_trigger(
    schedule="0 * * * * *", arg_name="myTimer", run_on_startup=False, use_monitor=False
)
def extract_fila(myTimer: func.TimerRequest) -> None:

    driver = "{ODBC Driver 18 for SQL Server}"
    host_sql = os.getenv("HOST")
    database_sql = os.getenv("DATABASE")
    user_sql = os.getenv("USER")
    pass_sql = os.getenv("PASSWORD")

    # string de conexao
    connection_string = (
        f"Driver={driver};"
        f"Server=tcp:{host_sql},1433;"
        f"Database={database_sql};"
        f"Uid={user_sql};"
        f"Pwd={pass_sql};"
        "Encrypt=yes;"
        "TrustServerCertificate=no;"
        "Connection Timeout=30;"
    )

    # tentativa de conexao
    try:
        conexao = pyodbc.connect(connection_string)
        cursor = conexao.cursor()

        logging.info("conectado com sucesso negão")

        query = "SELECT * FROM itsm.fila"

        cursor.execute(query)

        retorno = _upload_cursor_results(cursor, "fila", "filas")

        logging.info(retorno)

        cursor.close()
        conexao.close()
        logging.info("conexao fechada")
    except Exception as e:
        print(f"Erro ao conectar: {e}")


@app.timer_trigger(
    schedule="0 * * * * *", arg_name="myTimer", run_on_startup=False, use_monitor=False
)
def extract_sla(myTimer: func.TimerRequest) -> None:

    driver = "{ODBC Driver 18 for SQL Server}"
    host_sql = os.getenv("HOST")
    database_sql = os.getenv("DATABASE")
    user_sql = os.getenv("USER")
    pass_sql = os.getenv("PASSWORD")

    # string de conexao
    connection_string = (
        f"Driver={driver};"
        f"Server=tcp:{host_sql},1433;"
        f"Database={database_sql};"
        f"Uid={user_sql};"
        f"Pwd={pass_sql};"
        "Encrypt=yes;"
        "TrustServerCertificate=no;"
        "Connection Timeout=30;"
    )

    # tentativa de conexao
    try:
        conexao = pyodbc.connect(connection_string)
        cursor = conexao.cursor()

        logging.info("conectado com sucesso negão")

        query = "SELECT * FROM itsm.sla"

        cursor.execute(query)

        retorno = _upload_cursor_results(cursor, "sla", "slas")

        logging.info(retorno)

        cursor.close()
        conexao.close()
        logging.info("conexao fechada")
    except Exception as e:
        print(f"Erro ao conectar: {e}")


@app.timer_trigger(
    schedule="0 * * * * *", arg_name="myTimer", run_on_startup=False, use_monitor=False
)
def extract_solicitante(myTimer: func.TimerRequest) -> None:

    driver = "{ODBC Driver 18 for SQL Server}"
    host_sql = os.getenv("HOST")
    database_sql = os.getenv("DATABASE")
    user_sql = os.getenv("USER")
    pass_sql = os.getenv("PASSWORD")

    # string de conexao
    connection_string = (
        f"Driver={driver};"
        f"Server=tcp:{host_sql},1433;"
        f"Database={database_sql};"
        f"Uid={user_sql};"
        f"Pwd={pass_sql};"
        "Encrypt=yes;"
        "TrustServerCertificate=no;"
        "Connection Timeout=30;"
    )

    # tentativa de conexao
    try:
        conexao = pyodbc.connect(connection_string)
        cursor = conexao.cursor()

        logging.info("conectado com sucesso negão")

        query = "SELECT * FROM itsm.solicitante"

        cursor.execute(query)

        retorno = _upload_cursor_results(cursor, "solicitante", "solicitantes")

        logging.info(retorno)

        cursor.close()
        conexao.close()
        logging.info("conexao fechada")
    except Exception as e:
        print(f"Erro ao conectar: {e}")
