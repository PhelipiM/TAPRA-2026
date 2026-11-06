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
