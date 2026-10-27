
import snowflake.connector


def conectar():
    return snowflake.connector.connect(
        account="AXCNOLG-CU88061",
        user="nea.castroserrano",
        authenticator="OAUTH_AUTHORIZATION_CODE",
        database="SOURCE_DATA",
        schema="PUBLIC",
    )


if __name__ == "__main__":
    try:
        conn = conectar()
        print("¡Conexión con Snowflake exitosa!")
        print("Cuenta:", conn.cursor().execute(
            "SELECT CURRENT_ACCOUNT()"
        ).fetchone()[0])
        cursor = conn.cursor()
        cursor.execute("SELECT CURRENT_DATABASE(), CURRENT_SCHEMA()")
        print("Base de datos y esquema:", cursor.fetchone())
        cursor.close()
        conn.close()
    except Exception as error:
        print("Error de conexión:", error)
