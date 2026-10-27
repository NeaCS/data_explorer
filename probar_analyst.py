
import streamlit as st
import pandas as pd
import plotly.express as px
import requests

from conexion import conectar

SEMANTIC_VIEW = "SOURCE_DATA.PUBLIC.SOURCE_DATA_SV"
API_ENDPOINT = "/api/v2/cortex/analyst/message"

st.set_page_config(
    page_title="Dashboard de Exportaciones",
    page_icon="📊",
    layout="wide",
)

st.title("📊 Dashboard de Exportaciones")
st.caption("Análisis de exportaciones desde Snowflake")


# --------------------------------------------------
# FUNCIONES GENERALES
# --------------------------------------------------

def consultar_snowflake(sql):
    conn = conectar()
    try:
        cursor = conn.cursor()
        try:
            cursor.execute(sql)
            columnas = [columna[0] for columna in cursor.description]
            filas = cursor.fetchall()
            return pd.DataFrame(filas, columns=columnas)
        finally:
            cursor.close()
    finally:
        conn.close()


def formato_numero(valor, decimales=0):
    if pd.isna(valor):
        valor = 0

    return f"{valor:,.{decimales}f}".replace(",", "X").replace(".", ",").replace("X", ".")


def preparar_grafico(figura, altura=380):
    figura.update_layout(
        height=altura,
        margin=dict(l=20, r=20, t=45, b=20),
        template="plotly_white",
    )
    return figura


# --------------------------------------------------
# CARGA DEL DASHBOARD
# --------------------------------------------------

def cargar_indicadores():
    return consultar_snowflake("""
        SELECT *
        FROM SEMANTIC_VIEW(
            SOURCE_DATA.PUBLIC.SOURCE_DATA_SV
            METRICS
                total_fob_usd,
                total_kg,
                precio_promedio_usd_kg
        )
    """)


def cargar_paises():
    return consultar_snowflake("""
        SELECT *
        FROM SEMANTIC_VIEW(
            SOURCE_DATA.PUBLIC.SOURCE_DATA_SV
            DIMENSIONS pais_destino
            METRICS total_fob_usd, total_kg
        )
    """)


def cargar_frutas():
    return consultar_snowflake("""
        SELECT *
        FROM SEMANTIC_VIEW(
            SOURCE_DATA.PUBLIC.SOURCE_DATA_SV
            DIMENSIONS fruta
            METRICS total_fob_usd, total_kg
        )
    """)


def cargar_datos_mensuales():
    return consultar_snowflake("""
        SELECT
            DATE_TRUNC('MONTH', TRY_TO_DATE(FECHA)) AS MES,
            SUM(CANTIDAD_KG) AS TOTAL_KG,
            SUM(
                TRY_TO_DOUBLE(
                    REPLACE(
                        REPLACE(VALOR_FOB_USD, '$', ''),
                        ',',
                        ''
                    )
                )
            ) AS TOTAL_FOB_USD
        FROM SOURCE_DATA.PUBLIC.SOURCE_DATA
        WHERE TRY_TO_DATE(FECHA) IS NOT NULL
        GROUP BY 1
        ORDER BY 1
    """)


def cargar_exportadoras():
    return consultar_snowflake("""
        SELECT
            EXPORTADORA,
            SUM(CANTIDAD_KG) AS TOTAL_KG,
            SUM(
                TRY_TO_DOUBLE(
                    REPLACE(
                        REPLACE(VALOR_FOB_USD, '$', ''),
                        ',',
                        ''
                    )
                )
            ) AS TOTAL_FOB_USD
        FROM SOURCE_DATA.PUBLIC.SOURCE_DATA
        GROUP BY EXPORTADORA
        ORDER BY TOTAL_FOB_USD DESC
    """)


# --------------------------------------------------
# CORTEX ANALYST
# --------------------------------------------------

def consultar_cortex(pregunta, historial):
    conn = conectar()

    try:
        respuesta = requests.post(
            f"https://{conn.host}{API_ENDPOINT}",
            headers={
                "Authorization": f'Snowflake Token="{conn.rest.token}"',
                "Content-Type": "application/json",
            },
            json={
                "semantic_view": SEMANTIC_VIEW,
                "messages": historial + [
                    {
                        "role": "user",
                        "content": [
                            {
                                "type": "text",
                                "text": pregunta,
                            }
                        ],
                    }
                ],
            },
            timeout=60,
        )

        respuesta.raise_for_status()
        resultado = respuesta.json()

        contenido = resultado.get("message", {}).get("content", [])
        texto = []
        sql = None

        for bloque in contenido:
            if bloque.get("type") == "text":
                texto.append(bloque.get("text", ""))

            elif bloque.get("type") == "sql":
                sql = bloque.get("statement")

        resultado_df = None

        if sql:
            # Aceptamos únicamente SQL de lectura generado para
            # consultar la Semantic View configurada.
            sql_mayusculas = sql.upper()

            if (
                "SEMANTIC_VIEW(" not in sql_mayusculas
                or not sql_mayusculas.lstrip().startswith("SELECT")
                or ";" in sql.rstrip().rstrip(";")
            ):
                raise ValueError(
                    "Cortex Analyst generó una consulta que no "
                    "cumple las validaciones de lectura."
                )

            cursor = conn.cursor()
            try:
                cursor.execute(sql)
                columnas = [columna[0] for columna in cursor.description]
                filas = cursor.fetchall()
                resultado_df = pd.DataFrame(filas, columns=columnas)
            finally:
                cursor.close()

        return {
            "texto": "\n\n".join(texto).strip(),
            "sql": sql,
            "datos": resultado_df,
        }

    finally:
        conn.close()


# --------------------------------------------------
# PESTAÑAS
# --------------------------------------------------

tab_dashboard, tab_chatbot = st.tabs(["📊 Dashboard", "💬 Chatbot"])


# --------------------------------------------------
# DASHBOARD
# --------------------------------------------------

with tab_dashboard:
    if st.button("🔄 Actualizar dashboard"):
        st.rerun()

    try:
        with st.spinner("Consultando datos de Snowflake..."):
            indicadores = cargar_indicadores()
            paises = cargar_paises()
            frutas = cargar_frutas()
            meses = cargar_datos_mensuales()
            exportadoras = cargar_exportadoras()

        for df in [indicadores, paises, frutas, meses, exportadoras]:
            df.columns = df.columns.str.upper()

        if not indicadores.empty:
            fila = indicadores.iloc[0]

            total_fob = pd.to_numeric(
                fila.get("TOTAL_FOB_USD", 0), errors="coerce"
            )
            total_kg = pd.to_numeric(
                fila.get("TOTAL_KG", 0), errors="coerce"
            )
            precio_promedio = pd.to_numeric(
                fila.get("PRECIO_PROMEDIO_USD_KG", 0), errors="coerce"
            )

            total_fob = 0 if pd.isna(total_fob) else total_fob
            total_kg = 0 if pd.isna(total_kg) else total_kg
            precio_promedio = 0 if pd.isna(precio_promedio) else precio_promedio

            col1, col2, col3 = st.columns(3)
            col1.metric("Valor FOB total", f"US$ {formato_numero(total_fob, 2)}")
            col2.metric("Cantidad exportada", f"{formato_numero(total_kg)} kg")
            col3.metric("Precio promedio por kg", f"US$ {formato_numero(precio_promedio, 2)}")

        st.divider()
        st.subheader("Valor FOB por país de destino")

        if not paises.empty:
            paises["TOTAL_FOB_USD"] = pd.to_numeric(
                paises["TOTAL_FOB_USD"], errors="coerce"
            ).fillna(0)

            figura = px.bar(
                paises.sort_values("TOTAL_FOB_USD"),
                x="TOTAL_FOB_USD",
                y="PAIS_DESTINO",
                orientation="h",
                text="TOTAL_FOB_USD",
                labels={
                    "TOTAL_FOB_USD": "Valor FOB (USD)",
                    "PAIS_DESTINO": "País de destino",
                },
            )
            figura.update_traces(texttemplate="$%{x:,.0f}", textposition="outside")
            st.plotly_chart(preparar_grafico(figura, 450), use_container_width=True)

        col1, col2 = st.columns(2)

        with col1:
            st.subheader("Valor FOB por fruta")
            if not frutas.empty:
                frutas["TOTAL_FOB_USD"] = pd.to_numeric(
                    frutas["TOTAL_FOB_USD"], errors="coerce"
                ).fillna(0)

                figura = px.pie(
                    frutas,
                    names="FRUTA",
                    values="TOTAL_FOB_USD",
                    hole=0.4,
                )
                st.plotly_chart(preparar_grafico(figura), use_container_width=True)

        with col2:
            st.subheader("Evolución mensual del valor FOB")
            if not meses.empty:
                meses["MES"] = pd.to_datetime(meses["MES"], errors="coerce")
                meses["TOTAL_FOB_USD"] = pd.to_numeric(
                    meses["TOTAL_FOB_USD"], errors="coerce"
                ).fillna(0)
                meses = meses.dropna(subset=["MES"])

                figura = px.line(
                    meses.sort_values("MES"),
                    x="MES",
                    y="TOTAL_FOB_USD",
                    markers=True,
                    labels={
                        "MES": "Mes",
                        "TOTAL_FOB_USD": "Valor FOB (USD)",
                    },
                )
                st.plotly_chart(preparar_grafico(figura), use_container_width=True)

        st.subheader("Cantidad exportada por fruta")
        if not frutas.empty:
            frutas["TOTAL_KG"] = pd.to_numeric(
                frutas["TOTAL_KG"], errors="coerce"
            ).fillna(0)

            figura = px.bar(
                frutas.sort_values("TOTAL_KG"),
                x="TOTAL_KG",
                y="FRUTA",
                orientation="h",
                text="TOTAL_KG",
                labels={"TOTAL_KG": "Cantidad (kg)", "FRUTA": "Fruta"},
            )
            figura.update_traces(texttemplate="%{x:,.0f} kg", textposition="outside")
            st.plotly_chart(preparar_grafico(figura), use_container_width=True)

        st.subheader("Valor FOB por exportadora")
        if not exportadoras.empty:
            exportadoras["TOTAL_FOB_USD"] = pd.to_numeric(
                exportadoras["TOTAL_FOB_USD"], errors="coerce"
            ).fillna(0)

            figura = px.treemap(
                exportadoras,
                path=["EXPORTADORA"],
                values="TOTAL_FOB_USD",
                color="TOTAL_FOB_USD",
                labels={"TOTAL_FOB_USD": "Valor FOB (USD)"},
            )
            st.plotly_chart(preparar_grafico(figura, 420), use_container_width=True)

        with st.expander("Ver datos agregados"):
            st.markdown("**Países de destino**")
            st.dataframe(paises, use_container_width=True)
            st.markdown("**Frutas**")
            st.dataframe(frutas, use_container_width=True)
            st.markdown("**Datos mensuales**")
            st.dataframe(meses, use_container_width=True)
            st.markdown("**Exportadoras**")
            st.dataframe(exportadoras, use_container_width=True)

    except Exception as error:
        st.error(f"No se pudo cargar el dashboard: {error}")


# --------------------------------------------------
# CHATBOT
# --------------------------------------------------

with tab_chatbot:
    st.subheader("Consulta tus exportaciones")
    st.write("Haz preguntas en lenguaje natural sobre los datos de Snowflake.")

    if "historial_cortex" not in st.session_state:
        st.session_state.historial_cortex = []

    if "mensajes_chat" not in st.session_state:
        st.session_state.mensajes_chat = []

    for mensaje in st.session_state.mensajes_chat:
        with st.chat_message(mensaje["role"]):
            st.markdown(mensaje["content"])

            if mensaje.get("sql"):
                with st.expander("Ver SQL generado"):
                    st.code(mensaje["sql"], language="sql")

            if mensaje.get("datos") is not None:
                st.dataframe(mensaje["datos"], use_container_width=True)

    pregunta = st.chat_input("Ej.: ¿Qué país tiene el mayor valor FOB?")

    if pregunta:
        st.session_state.mensajes_chat.append({
            "role": "user",
            "content": pregunta,
        })

        with st.chat_message("user"):
            st.markdown(pregunta)

        try:
            with st.spinner("Cortex Analyst está analizando la pregunta..."):
                resultado = consultar_cortex(
                    pregunta,
                    st.session_state.historial_cortex,
                )

            respuesta_texto = resultado["texto"] or (
                "Cortex Analyst generó una consulta SQL."
                if resultado["sql"]
                else "Cortex Analyst no devolvió una respuesta textual ni SQL."
            )

            with st.chat_message("assistant"):
                st.markdown(respuesta_texto)

                if resultado["sql"]:
                    with st.expander("Ver SQL generado"):
                        st.code(resultado["sql"], language="sql")

                if resultado["datos"] is not None:
                    st.dataframe(resultado["datos"], use_container_width=True)

            st.session_state.mensajes_chat.append({
                "role": "assistant",
                "content": respuesta_texto,
                "sql": resultado["sql"],
                "datos": resultado["datos"],
            })

            # Mantiene el contexto de mensajes para las preguntas siguientes.
            st.session_state.historial_cortex.extend([
                {
                    "role": "user",
                    "content": [{"type": "text", "text": pregunta}],
                },
                {
                    "role": "assistant",
                    "content": [
                        {
                            "type": "text",
                            "text": respuesta_texto,
                        }
                    ],
                },
            ])

        except Exception as error:
            st.error(f"No se pudo consultar Cortex Analyst: {error}")

    if st.button("Limpiar conversación"):
        st.session_state.historial_cortex = []
        st.session_state.mensajes_chat = []
        st.rerun()
