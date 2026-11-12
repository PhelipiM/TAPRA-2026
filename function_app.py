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


# A carga é separada das funções extract_*: elas continuam exportando do banco
# configurado em DATABASE para o Data Lake. Esta função carrega para DATABASE_SLK.
_INGEST_TABLES = {
    "analistas": "analista",
    "categorias": "categoria",
    "chamados": "chamado",
    "chamados_sla": "chamado_sla",
    "chamados_status_historico": "chamado_status_historico",
    "clientes_organizacao": "cliente_organizacao",
    "csat_avaliacoes": "csat_avaliacao",
    "filas": "fila",
    "slas": "sla",
    "solicitantes": "solicitante",
}


def _ingest_sql_connection():
    host_sql = os.getenv("HOST")
    database_sql = os.getenv("DATABASE_SLK", "").strip()
    if len(database_sql) >= 2 and database_sql[0] == database_sql[-1] and database_sql[0] in ("'", '"'):
        database_sql = database_sql[1:-1].strip()
    user_sql = os.getenv("USER")
    password_sql = os.getenv("PASSWORD")
    missing = [
        name for name, value in (
            ("HOST", host_sql), ("DATABASE_SLK", database_sql),
            ("USER", user_sql), ("PASSWORD", password_sql),
        ) if not value
    ]
    if missing:
        raise ValueError(f"Variáveis de ambiente ausentes: {', '.join(missing)}")
    if ";" in database_sql:
        raise ValueError(
            "DATABASE_SLK deve conter somente o nome do banco (por exemplo, db-tapra), "
            "sem ponto e vírgula nem connection string."
        )
    logging.info("Banco SQL de destino da ingestão: %s", database_sql)

    connection_string = (
        "DRIVER={ODBC Driver 18 for SQL Server};"
        f"SERVER=tcp:{host_sql},1433;"
        f"DATABASE={database_sql};"
        f"UID={user_sql};"
        f"PWD={password_sql};"
        "Encrypt=yes;TrustServerCertificate=no;Connection Timeout=30;"
    )
    return pyodbc.connect(connection_string)


def _insert_json_records(cursor, table_name: str, records: list) -> int:
    if not isinstance(records, list):
        raise ValueError("O JSON deve conter uma lista de objetos.")
    if not records:
        return 0
    if any(not isinstance(record, dict) for record in records):
        raise ValueError("Cada item do JSON deve ser um objeto.")

    columns = list(records[0].keys())
    if not columns or any(
        not isinstance(column, str)
        or not column.replace("_", "a").isalnum()
        or not column[0].isalpha()
        for column in columns
    ):
        raise ValueError("O JSON contém nome de coluna inválido.")
    if any(set(record.keys()) != set(columns) for record in records):
        raise ValueError("Os objetos do JSON não têm as mesmas colunas.")

    quoted_columns = ", ".join(f"[{column}]" for column in columns)
    placeholders = ", ".join("?" for _ in columns)
    statement = (
        f"INSERT INTO [itsm].[{table_name}] ({quoted_columns}) "
        f"VALUES ({placeholders})"
    )

    def sql_value(value):
        if isinstance(value, (dict, list)):
            return json.dumps(value, ensure_ascii=False)
        return value

    cursor.execute(
        """
        SELECT c.name
        FROM sys.columns AS c
        INNER JOIN sys.tables AS t ON t.object_id = c.object_id
        INNER JOIN sys.schemas AS s ON s.schema_id = t.schema_id
        WHERE s.name = ? AND t.name = ? AND c.is_identity = 1
        """,
        "itsm",
        table_name,
    )
    identity_column = cursor.fetchone()
    copy_identity = identity_column is not None and identity_column[0] in columns

    if copy_identity:
        cursor.execute(f"SET IDENTITY_INSERT [itsm].[{table_name}] ON")
    try:
        # fast_executemany infere os tipos pela primeira linha e pode converter
        # incorretamente strings ISO/nulos exportados para colunas SQL tipadas.
        # A carga inicial prioriza conversão correta; executemany padrão envia os
        # parâmetros usando a conversão normal do driver ODBC.
        cursor.fast_executemany = False
        cursor.executemany(
            statement,
            [tuple(sql_value(record[column]) for column in columns) for record in records],
        )
    finally:
        if copy_identity:
            cursor.execute(f"SET IDENTITY_INSERT [itsm].[{table_name}] OFF")
    return len(records)


@app.route(route="ingest-datalake", methods=["POST"], auth_level=func.AuthLevel.FUNCTION)
def ingest_datalake_jsons(req: func.HttpRequest) -> func.HttpResponse:
    """Carga manual: importa o snapshot JSON mais recente de cada tabela para DATABASE_SLK."""
    datalake_connection = os.getenv("DATALAKE_CONNECTION_STRING")
    if not datalake_connection:
        raise ValueError("A configuração DATALAKE_CONNECTION_STRING não foi definida.")

    datalake = DataLakeServiceClient.from_connection_string(datalake_connection)
    loaded_files = 0
    loaded_rows = 0
    failures = []
    try:
        filesystem = datalake.get_file_system_client("bronze")
        # Os arquivos são snapshots completos (SELECT *), então usa só o mais
        # recente de cada entidade e arquiva os snapshots antigos para evitar
        # inserir as mesmas linhas repetidamente.
        latest_by_entity = {}
        for item in filesystem.get_paths():
            path = item.name
            if not path.lower().endswith(".json") or "/_processados/" in f"/{path}/":
                continue
            entity = next((part for part in path.split("/") if part in _INGEST_TABLES), None)
            if not entity:
                continue
            previous = latest_by_entity.get(entity)
            modified = item.last_modified
            if previous is None or modified > previous[0]:
                latest_by_entity[entity] = (modified, path)

        for entity, (_, latest_path) in latest_by_entity.items():
            table_name = _INGEST_TABLES[entity]
            entity_files = [
                item.name for item in filesystem.get_paths()
                if item.name.lower().endswith(".json")
                and entity in item.name.split("/")
                and "/_processados/" not in f"/{item.name}/"
            ]
            for path in entity_files:
                try:
                    file_client = filesystem.get_file_client(path)
                    if path == latest_path:
                        payload = file_client.download_file().readall()
                        records = json.loads(payload.decode("utf-8-sig"))
                        with _ingest_sql_connection() as connection:
                            cursor = connection.cursor()
                            row_count = _insert_json_records(cursor, table_name, records)
                            cursor.close()
                            connection.commit()
                        loaded_files += 1
                        loaded_rows += row_count
                        logging.info("Importado %s: %s linhas em itsm.%s", path, row_count, table_name)

                    directory = path.rsplit("/", 1)[0] if "/" in path else ""
                    processed_dir = f"{directory}/_processados" if directory else "_processados"
                    try:
                        filesystem.get_directory_client(processed_dir).create_directory()
                    except Exception:
                        pass
                    destination = f"{processed_dir}/{path.rsplit('/', 1)[-1]}"
                    file_client.rename_file(f"bronze/{destination}")
                except Exception as exc:
                    failures.append({"arquivo": path, "erro": f"{type(exc).__name__}: {exc}"})
                    logging.exception("Falha ao importar/arquivar %s", path)

        summary = {
            "arquivos_importados": loaded_files,
            "linhas_importadas": loaded_rows,
            "falhas": failures,
        }
        logging.info("Ingestão concluída: %s", summary)
        return func.HttpResponse(
            json.dumps(summary, ensure_ascii=False),
            status_code=500 if failures else 200,
            mimetype="application/json",
        )
    finally:
        datalake.close()


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
