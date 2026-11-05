import csv
import io
import logging
import os
from datetime import datetime, timezone

import pyodbc
import azure.functions as func
from azure.storage.filedatalake import DataLakeServiceClient

app = func.FunctionApp()


@app.timer_trigger(
    schedule="0 */3 * * * *",
    arg_name="myTimer",
    run_on_startup=False,
    use_monitor=False,
)
def timer_trigger_taprafunc1(myTimer: func.TimerRequest) -> None:
    if myTimer.past_due:
        logging.info("Eita, demorou demais!")

    logging.info("Aqui é o timer trigger, rodando a cada 3 minutos!")


@app.route(route="http_trigger", auth_level=func.AuthLevel.ANONYMOUS)
def http_trigger(req: func.HttpRequest) -> func.HttpResponse:
    logging.info("Python HTTP trigger function processed a request.")

    name = req.params.get("name")
    if not name:
        return func.HttpResponse("Informe o parametro name na URL.", status_code=400)

    logging.info(f"Parametro recebido: {name}")

    return func.HttpResponse(
        f"Informacao recebida: {name}. Esta mensagem foi retornada pela HTTP Function."
    )


@app.timer_trigger(
    schedule="0 */5 * * * *",
    arg_name="myTimer",
    run_on_startup=False,
    use_monitor=False,
)
def timer_trigger_http(myTimer: func.TimerRequest) -> None:

    logging.info("Iniciando a time trigger http")

    host = os.environ.get("WEBSITE_HOSTNAME")
    url = f"https://{host}/api/http_trigger"

    payload = {"name": "nome exemplo"}

    try:
        response = requests.get(url, params=payload, timeout=10)
        response.raise_for_status()

        logging.info(
            f"Timer trigger chamou a HTTP function. Status: {response.status_code} | Retorno: {response.text}"
        )
    except Exception as e:
        logging.error(f"Falha ao tentar se comunicar com a função interna: {str(e)}")

    logging.info("Finalizando a time trigger http")


@app.timer_trigger(
    schedule="0 * * * * *", arg_name="myTimer", run_on_startup=False, use_monitor=False
)
def extract_chamado(myTimer: func.TimerRequest) -> None:
     logging.info('tabela chamado')

    
    host_sql = os.getenv("HOST")
    database_sql = os.getenv("DATABASE")
    user_sql = os.getenv("USER")
    pass_sql = os.getenv("PASSWORD")

    logging.info(f'servidor={host_sql}, banco de dados={database_sql}, usuario={user_sql}, senha={pass_sql} ')

    # string de conexao
     conn_str = (
        "DRIVER={ODBC Driver 18 for SQL Server};"
        f"SERVER={host_sql};"
        f"DATABASE={database_sql};"
        f"UID={user_sql};"
        f"PWD={pass_sql};"
        "Encrypt=yes;"
        "TrustServerCertificate=no;"
        "Connection Timeout=30;"
    )


     try:
        # Estabelece a conexão com o banco de dados usando pyodbc
        with pyodbc.connect(conn_str) as conn:
            # Cria um cursor para executar a consulta
            cursor = conn.cursor()
            
            query = "select * from itsm.chamado"

            # Executa a consulta SQL
            cursor.execute(query)

            # Busca todos os resultados da consulta
            rows = cursor.fetchall()
            columns = [col[0] for col in cursor.description]

            logging.info(f'{len(rows)} linhas lidas de itsm.chamado')

        # Cria um buffer de memória para armazenar os dados CSV
        buffer = io.StringIO()
        # Cria um objeto CSV writer e escreve os dados no buffer
        writer = csv.writer(buffer)
        # Escreve o cabeçalho e as linhas no buffer CSV
        writer.writerow(columns)
        # Escreve todas as linhas no buffer CSV
        writer.writerows(rows)

        # Grava o arquivo no contêiner bronze do Data Lake, particionado por data
        now = datetime.now(timezone.utc)
        file_path = f"chamado/{now:%Y/%m/%d}/chamado_{now:%Y%m%d_%H%M%S}.csv"

        #itsm/chamado/year=2024/month=06/day=05/chamado_20240605_123456.csv
        #file_path = f"itsm/chamado/year={now:%Y}/month={now:%m}/day={now:%d}/chamado_{now:%Y%m%d_%H%M%S}.csv"

        # Cria o cliente do Data Lake e grava o arquivo no contêiner bronze
        datalake = DataLakeServiceClient.from_connection_string(os.getenv("DATALAKE_CONNECTION_STRING"))
        # Cria o cliente do sistema de arquivos e grava o arquivo no contêiner bronze
        file_client = datalake.get_file_system_client("bronze").get_file_client(file_path)
        # Grava os dados do buffer no arquivo do Data Lake, sobrescrevendo se já existir
        file_client.upload_data(buffer.getvalue().encode("utf-8"), overwrite=True)

        logging.info(f'Arquivo gravado em bronze/{file_path}')

    except Exception as e:
        logging.error(f"Erro ao ler itsm.chamado: {str(e)}")
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

        retorno = cursor.fetchall()

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

        retorno = cursor.fetchall()

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

        retorno = cursor.fetchall()

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

        retorno = cursor.fetchall()

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

        retorno = cursor.fetchall()

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

        retorno = cursor.fetchall()

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

        retorno = cursor.fetchall()

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

        retorno = cursor.fetchall()

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

        retorno = cursor.fetchall()

        logging.info(retorno)

        cursor.close()
        conexao.close()
        logging.info("conexao fechada")
    except Exception as e:
        print(f"Erro ao conectar: {e}")
