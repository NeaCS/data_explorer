import re

import pandas as pd
import plotly.express as px
import requests
import streamlit as st

from conexion import conectar


# --------------------------------------------------
# CONFIGURACIÓN
# --------------------------------------------------

st.set_page_config(
    page_title="Dashboard de Exportaciones",
    page_icon="📊",
    layout="wide",
)

APP_BG = st.get_option("theme.backgroundColor")
if not APP_BG:
    APP_BG = "#0e1117" if st.context.theme.type == "dark" else "#ffffff"

NAVBAR_CSS = """
<style>
[data-testid="stTabs"] [role="tablist"] {
    position: fixed !important;
    top: 3.5rem !important;
    left: 0;
    right: 0;
    z-index: 2000;
    padding: .35rem 1rem 0;
    background-color: __APP_BG__ !important;
}
</style>
""".replace("__APP_BG__", APP_BG)
st.markdown(NAVBAR_CSS, unsafe_allow_html=True)
SEMANTIC_VIEW = "SOURCE_DATA.PUBLIC.SOURCE_DATA_SV"
API_ENDPOINT = "/api/v2/cortex/analyst/message"

# Número de mensajes anteriores que se envían para conservar el contexto.
MAX_MENSAJES_HISTORIAL = 12


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


def preparar_grafico(figura, altura=380):
    figura.update_layout(
        height=altura,
        margin=dict(l=20, r=20, t=55, b=20),
        template="plotly_white",
    )
    return figura


def formato_numero(valor, decimales=0):
    valor = pd.to_numeric(valor, errors="coerce")

    if pd.isna(valor):
        valor = 0

    return (
        f"{valor:,.{decimales}f}"
        .replace(",", "X")
        .replace(".", ",")
        .replace("X", ".")
    )


# --------------------------------------------------
# RESUMEN LOCAL DE RESULTADOS
# --------------------------------------------------

def generar_resumen(datos, pregunta):
    if datos is None or datos.empty:
        return "La consulta no devolvió resultados para analizar."

    df = datos.copy()
    df.columns = df.columns.str.upper()
    pregunta_lower = pregunta.lower()

    palabras_kilos = ["kilos", "kg", "cantidad", "volumen"]
    palabras_precio = [
        "precio promedio",
        "precio por kilo",
        "precio por kg",
    ]
    palabras_fob = ["fob", "valor", "ventas", "ingresos"]

    if any(palabra in pregunta_lower for palabra in palabras_precio):
        preferencias = ["PRECIO PROMEDIO", "PRECIO USD"]
        unidad = "US$ por kg"
    elif any(palabra in pregunta_lower for palabra in palabras_kilos):
        preferencias = ["TOTAL KG", "CANTIDAD", "KILOS"]
        unidad = "kg"
    elif any(palabra in pregunta_lower for palabra in palabras_fob):
        preferencias = ["TOTAL FOB", "VALOR FOB", "FOB"]
        unidad = "US$"
    else:
        preferencias = []
        unidad = ""

    metricas = []

    for columna in df.columns:
        convertida = pd.to_numeric(df[columna], errors="coerce")

        if convertida.notna().any():
            metricas.append(columna)
            df[columna] = convertida

    if not metricas:
        return (
            f"La consulta devolvió {len(df)} resultados. "
            "Revisa la tabla para consultar el detalle."
        )

    valor = None

    for preferencia in preferencias:
        valor = next(
            (
                columna for columna in metricas
                if preferencia in columna.replace("_", " ")
            ),
            None,
        )

        if valor:
            break

    if valor is None:
        valor = metricas[0]

    df = df.dropna(subset=[valor])

    if df.empty:
        return "No hay valores numéricos válidos para resumir."

    nombre_metrica = valor.replace("_", " ").lower()
    categorias = [
        columna for columna in df.columns
        if columna != valor and columna not in metricas
    ]

    pide_porcentaje = any(
        palabra in pregunta_lower
        for palabra in [
            "porcentaje",
            "proporción",
            "proporcion",
            "participación",
            "participacion",
        ]
    )

    if pide_porcentaje and categorias:
        total = df[valor].sum()

        if total != 0:
            categoria = categorias[0]
            indice = df[valor].idxmax()
            nombre = str(df.loc[indice, categoria])
            maximo = df.loc[indice, valor]
            porcentaje = maximo / total * 100

            return (
                f"**{nombre}** representa la mayor participación, "
                f"con **{formato_numero(porcentaje, 2)} %** "
                f"del total de {nombre_metrica}. "
                f"Su valor es {formato_numero(maximo, 2)} {unidad}."
            )

    if categorias and len(df) > 1:
        categoria = categorias[0]
        indice = df[valor].idxmax()
        nombre = str(df.loc[indice, categoria])
        maximo = df.loc[indice, valor]

        return (
            f"Según los resultados, **{nombre}** registra el mayor "
            f"valor de {nombre_metrica}, con "
            f"**{formato_numero(maximo, 2)} {unidad}**. "
            f"La consulta incluye {len(df)} resultados."
        )

    if len(df) == 1:
        valor_unico = df[valor].iloc[0]

        if categorias:
            categoria = categorias[0]
            nombre = str(df[categoria].iloc[0])

            return (
                f"Según los resultados, **{nombre}** registra "
                f"**{formato_numero(valor_unico, 2)} {unidad}** "
                f"de {nombre_metrica}."
            )

        return (
            f"El resultado de {nombre_metrica} es "
            f"**{formato_numero(valor_unico, 2)} {unidad}**."
        )

    total = df[valor].sum()

    return (
        f"La consulta contiene {len(df)} registros. "
        f"La suma de {nombre_metrica} es "
        f"**{formato_numero(total, 2)} {unidad}**."
    )


# --------------------------------------------------
# GRÁFICOS PARA RESULTADOS DEL CHATBOT
# --------------------------------------------------

def generar_grafico_chat(datos, pregunta):
    if datos is None or datos.empty or len(datos.columns) < 2:
        return None

    df = datos.copy()
    df.columns = df.columns.str.upper()
    pregunta_lower = pregunta.lower()

    def normalizar(texto):
        return str(texto).lower().replace("_", " ").strip()

    temporal = None

    for columna in df.columns:
        nombre = normalizar(columna)

        if any(
            palabra in nombre
            for palabra in ["fecha", "mes", "año", "anio", "year", "date"]
        ):
            fechas = pd.to_datetime(df[columna], errors="coerce")

            if fechas.notna().all() and len(fechas) > 0:
                df[columna] = fechas
                temporal = columna
                break

    metricas = []

    for columna in df.columns:
        if columna == temporal:
            continue

        nombre = normalizar(columna)
        parece_metrica = any(
            palabra in nombre
            for palabra in [
                "total fob",
                "valor fob",
                "fob",
                "total kg",
                "cantidad",
                "kilos",
                "precio promedio",
                "precio usd",
                "total",
                "valor",
                "porcentaje",
            ]
        )

        convertida = pd.to_numeric(df[columna], errors="coerce")

        if convertida.notna().any() and parece_metrica:
            df[columna] = convertida
            metricas.append(columna)

    if not metricas:
        for columna in df.columns:
            if columna == temporal:
                continue

            convertida = pd.to_numeric(df[columna], errors="coerce")

            if convertida.notna().any():
                df[columna] = convertida
                metricas.append(columna)

    if not metricas:
        return None

    pide_kilos = any(
        palabra in pregunta_lower
        for palabra in ["kilos", "kg", "cantidad", "volumen"]
    )
    pide_precio = any(
        palabra in pregunta_lower
        for palabra in ["precio promedio", "precio por kilo", "precio por kg"]
    )
    pide_fob = any(
        palabra in pregunta_lower
        for palabra in ["fob", "valor", "ventas", "ingresos"]
    )

    if pide_precio:
        preferencias = ["PRECIO PROMEDIO", "PRECIO USD"]
    elif pide_kilos:
        preferencias = ["TOTAL KG", "CANTIDAD", "KILOS"]
    elif pide_fob:
        preferencias = ["TOTAL FOB", "VALOR FOB", "FOB"]
    else:
        preferencias = []

    valor = None

    for preferencia in preferencias:
        valor = next(
            (
                columna for columna in metricas
                if preferencia in normalizar(columna).upper()
            ),
            None,
        )

        if valor:
            break

    if valor is None:
        valor = metricas[0]

    pide_evolucion = any(
        palabra in pregunta_lower
        for palabra in [
            "evolución",
            "evolucion",
            "tendencia",
            "histórico",
            "historico",
            "mensual",
            "por mes",
            "por año",
            "anual",
            "a través del tiempo",
            "con el tiempo",
        ]
    )

    if temporal and pide_evolucion:
        df = df.dropna(subset=[temporal, valor]).sort_values(temporal)

        if df.empty:
            return None

        figura = px.line(
            df,
            x=temporal,
            y=valor,
            markers=True,
            title=f"Evolución de {normalizar(valor)}",
            labels={
                temporal: normalizar(temporal).title(),
                valor: normalizar(valor).title(),
            },
        )

        return preparar_grafico(figura)

    categorias = [
        columna for columna in df.columns
        if columna != temporal and columna not in metricas
    ]

    if not categorias:
        return None

    categoria = categorias[0]
    pide_proporcion = any(
        palabra in pregunta_lower
        for palabra in [
            "porcentaje",
            "proporción",
            "proporcion",
            "participación",
            "participacion",
            "distribución",
            "distribucion",
        ]
    )

    if pide_proporcion and 2 <= len(df) <= 10:
        df = df.dropna(subset=[categoria, valor])

        if df.empty:
            return None

        figura = px.pie(
            df,
            names=categoria,
            values=valor,
            hole=0.35,
            title=f"Distribución de {normalizar(valor)}",
        )

        return preparar_grafico(figura)

    df[valor] = pd.to_numeric(df[valor], errors="coerce")
    df = df.dropna(subset=[categoria, valor]).sort_values(
        valor,
        ascending=True,
    )

    if df.empty:
        return None

    figura = px.bar(
        df,
        x=valor,
        y=categoria,
        orientation="h",
        title=f"{normalizar(valor).title()} por {normalizar(categoria)}",
        labels={
            valor: normalizar(valor).title(),
            categoria: normalizar(categoria).title(),
        },
    )

    return preparar_grafico(
        figura,
        max(380, min(600, len(df) * 35)),
    )


# --------------------------------------------------
# CONSULTAS DEL DASHBOARD
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
# VALIDACIÓN Y CONTEXTO DE CORTEX ANALYST
# --------------------------------------------------

def validar_sql_analyst(sql):
    if not sql or not isinstance(sql, str):
        raise ValueError("Cortex Analyst no devolvió una consulta SQL.")

    sql_limpio = sql.strip().rstrip(";")

    # Se rechaza cualquier comentario o más de una sentencia.
    if ";" in sql_limpio:
        raise ValueError("La consulta generada contiene más de una sentencia.")

    sin_comentarios = re.sub(
        r"/\*.*?\*/|--[^\r\n]*",
        " ",
        sql_limpio,
        flags=re.DOTALL,
    ).strip()

    empieza_con_select = re.match(
        r"^SELECT\b",
        sin_comentarios,
        flags=re.IGNORECASE,
    )
    empieza_con_cte = re.match(
        r"^WITH\b",
        sin_comentarios,
        flags=re.IGNORECASE,
    )
    contiene_select = re.search(
        r"\bSELECT\b",
        sin_comentarios,
        flags=re.IGNORECASE,
    )

    if not (empieza_con_select or (empieza_con_cte and contiene_select)):
        raise ValueError("Solo se permiten consultas SELECT.")

    # Acepta identificadores entre comillas y referencias directas a la
    # misma vista semántica, pero no permite cambiar a otra tabla.
    sql_sin_comillas = sin_comentarios.replace('"', "")
    vista_autorizada = re.search(
        r"\bFROM\s+(?:SEMANTIC_VIEW\s*\(\s*)?"
        r"'?SOURCE_DATA\s*\.\s*PUBLIC\s*\.\s*SOURCE_DATA_SV'?\b",
        sql_sin_comillas,
        flags=re.IGNORECASE,
    )

    if not vista_autorizada:
        raise ValueError(
            "La consulta debe usar la vista semántica autorizada."
        )

    palabras_no_permitidas = re.search(
        r"\b(INSERT|UPDATE|DELETE|MERGE|CREATE|ALTER|DROP|"
        r"TRUNCATE|COPY|PUT|GET|CALL|EXECUTE|GRANT|REVOKE)\b",
        sin_comentarios,
        flags=re.IGNORECASE,
    )

    if palabras_no_permitidas:
        raise ValueError("La consulta contiene una operación no permitida.")

    return sql_limpio


def construir_historial_para_analyst(mensajes_chat):
    """
    Convierte el historial visible de Streamlit al formato de Cortex Analyst.

    Analyst recibe historial de mensajes, pero no tiene acceso automático
    a los resultados completos de las consultas SQL anteriores.
    """
    anteriores = mensajes_chat[:-1][-MAX_MENSAJES_HISTORIAL:]
    historial = []

    for mensaje in anteriores:
        if mensaje.get("role") == "user":
            historial.append({
                "role": "user",
                "content": [
                    {
                        "type": "text",
                        "text": mensaje.get("content", ""),
                    }
                ],
            })

        elif mensaje.get("role") == "assistant":
            contenido = mensaje.get("contenido")

            if contenido:
                historial.append({
                    "role": "analyst",
                    "content": contenido,
                })
            else:
                historial.append({
                    "role": "analyst",
                    "content": [
                        {
                            "type": "text",
                            "text": mensaje.get("content", ""),
                        }
                    ],
                })

    return historial


INTERPRETACION_ANALYST = re.compile(
    r"^\s*This is our interpretation of your question:\s*.*?(?:\r?\n\s*\r?\n|$)",
    flags=re.IGNORECASE | re.DOTALL,
)


def limpiar_texto_analyst(texto):
    if not texto:
        return ""
    return INTERPRETACION_ANALYST.sub("", str(texto), count=1).strip()

def consultar_cortex(pregunta, mensajes_chat):
    conn = conectar()

    try:
        url = f"https://{conn.host}{API_ENDPOINT}"
        historial = construir_historial_para_analyst(mensajes_chat)

        mensajes_api = historial + [
            {
                "role": "user",
                "content": [
                    {
                        "type": "text",
                        "text": pregunta,
                    }
                ],
            }
        ]

        respuesta = requests.post(
            url,
            headers={
                "Authorization": f'Snowflake Token="{conn.rest.token}"',
                "Content-Type": "application/json",
            },
            json={
                "semantic_view": SEMANTIC_VIEW,
                "messages": mensajes_api,
            },
            timeout=60,
        )

        if not respuesta.ok:
            try:
                detalle = respuesta.json()
            except ValueError:
                detalle = respuesta.text

            raise RuntimeError(
                f"Snowflake respondió HTTP {respuesta.status_code}: {detalle}"
            )

        resultado = respuesta.json()
        mensaje = resultado.get("message", {})
        contenido = mensaje.get("content", [])

        textos = []
        sugerencias = []
        sql = None

        for bloque in contenido:
            tipo = bloque.get("type")

            if tipo == "text":
                texto = bloque.get("text", "")
                if texto:
                    textos.append(texto)

            elif tipo == "sql":
                sql = bloque.get("statement")

            elif tipo in ("suggestion", "suggestions"):
                opciones = bloque.get("suggestions", [])

                if isinstance(opciones, list):
                    sugerencias.extend(
                        str(opcion) for opcion in opciones if opcion
                    )

                texto_sugerencia = bloque.get("text")
                if texto_sugerencia:
                    sugerencias.append(str(texto_sugerencia))

        datos = None
        sql_validado = None

        if sql:
            sql_validado = validar_sql_analyst(sql)
            cursor = conn.cursor()

            try:
                cursor.execute(sql_validado)
                columnas = [
                    columna[0] for columna in cursor.description
                ]
                datos = pd.DataFrame(
                    cursor.fetchall(),
                    columns=columnas,
                )
            finally:
                cursor.close()

        texto = "\n\n".join(item for item in textos if item).strip()
        texto = limpiar_texto_analyst(texto)

        if not texto and sugerencias:
            texto = "Necesito un poco más de detalle. Prueba con una de estas preguntas:"
        elif not texto and sql:
            texto = ""
        elif not texto:
            texto = "Cortex Analyst no devolvió una respuesta."

        return {
            "texto": texto,
            "sql": sql_validado,
            "datos": datos,
            "contenido": contenido,
            "sugerencias": sugerencias,
        }

    finally:
        conn.close()


# --------------------------------------------------
# PESTAÑAS
# --------------------------------------------------

tab_dashboard, tab_chatbot = st.tabs(["Dashboard", "Chatbot"])


# --------------------------------------------------
# DASHBOARD
# --------------------------------------------------

with tab_dashboard:
    if st.button("Actualizar dashboard"):
        st.rerun()

    try:
        with st.spinner("Cargando datos desde Snowflake..."):
            indicadores = cargar_indicadores()
            paises = cargar_paises()
            frutas = cargar_frutas()
            meses = cargar_datos_mensuales()
            exportadoras = cargar_exportadoras()

        for df in [indicadores, paises, frutas, meses, exportadoras]:
            df.columns = df.columns.str.upper()

        if not indicadores.empty:
            fila = indicadores.iloc[0]
            total_fob = fila.get("TOTAL_FOB_USD", 0)
            total_kg = fila.get("TOTAL_KG", 0)
            precio_promedio = fila.get("PRECIO_PROMEDIO_USD_KG")

            if pd.isna(precio_promedio):
                precio_promedio = (
                    float(total_fob) / float(total_kg)
                    if float(total_kg) != 0 else 0
                )

            col1, col2, col3 = st.columns(3)

            col1.metric(
                "Valor FOB total",
                f"US$ {formato_numero(total_fob, 2)}",
            )
            col2.metric(
                "Cantidad exportada",
                f"{formato_numero(total_kg)} kg",
            )
            col3.metric(
                "Precio promedio por kg",
                f"US$ {formato_numero(precio_promedio, 2)}",
            )

        st.divider()
        st.subheader("Valor FOB por país de destino")

        if not paises.empty:
            paises["TOTAL_FOB_USD"] = pd.to_numeric(
                paises["TOTAL_FOB_USD"],
                errors="coerce",
            ).fillna(0)

            figura = px.bar(
                paises.sort_values("TOTAL_FOB_USD"),
                x="TOTAL_FOB_USD",
                y="PAIS_DESTINO",
                orientation="h",
                labels={
                    "TOTAL_FOB_USD": "Valor FOB (USD)",
                    "PAIS_DESTINO": "País de destino",
                },
            )

            st.plotly_chart(
                preparar_grafico(figura, 450),
                width="stretch",
            )
        else:
            st.info("No hay datos por país.")

        col1, col2 = st.columns(2)

        with col1:
            st.subheader("Valor FOB por fruta")

            if not frutas.empty:
                frutas["TOTAL_FOB_USD"] = pd.to_numeric(
                    frutas["TOTAL_FOB_USD"],
                    errors="coerce",
                ).fillna(0)

                figura = px.pie(
                    frutas,
                    names="FRUTA",
                    values="TOTAL_FOB_USD",
                    hole=0.4,
                )

                st.plotly_chart(
                    preparar_grafico(figura),
                    width="stretch",
                )
            else:
                st.info("No hay datos por fruta.")

        with col2:
            st.subheader("Evolución mensual del valor FOB")

            if not meses.empty:
                meses["MES"] = pd.to_datetime(
                    meses["MES"],
                    errors="coerce",
                )
                meses["TOTAL_FOB_USD"] = pd.to_numeric(
                    meses["TOTAL_FOB_USD"],
                    errors="coerce",
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

                st.plotly_chart(
                    preparar_grafico(figura),
                    width="stretch",
                )
            else:
                st.info("No hay datos mensuales.")

        st.subheader("Cantidad exportada por fruta")

        if not frutas.empty:
            frutas["TOTAL_KG"] = pd.to_numeric(
                frutas["TOTAL_KG"],
                errors="coerce",
            ).fillna(0)

            figura = px.bar(
                frutas.sort_values("TOTAL_KG"),
                x="TOTAL_KG",
                y="FRUTA",
                orientation="h",
                labels={
                    "TOTAL_KG": "Cantidad (kg)",
                    "FRUTA": "Fruta",
                },
            )

            st.plotly_chart(
                preparar_grafico(figura),
                width="stretch",
            )

        st.subheader("Valor FOB por exportadora")

        if not exportadoras.empty:
            exportadoras["TOTAL_FOB_USD"] = pd.to_numeric(
                exportadoras["TOTAL_FOB_USD"],
                errors="coerce",
            ).fillna(0)

            figura = px.treemap(
                exportadoras,
                path=["EXPORTADORA"],
                values="TOTAL_FOB_USD",
            )

            st.plotly_chart(
                preparar_grafico(figura, 420),
                width="stretch",
            )

        with st.expander("Ver datos agregados"):
            st.markdown("**Países de destino**")
            st.dataframe(paises, width="stretch")

            st.markdown("**Frutas**")
            st.dataframe(frutas, width="stretch")

            st.markdown("**Datos mensuales**")
            st.dataframe(meses, width="stretch")

            st.markdown("**Exportadoras**")
            st.dataframe(exportadoras, width="stretch")

    except Exception as error:
        st.error(f"No se pudo cargar el dashboard: {error}")


# --------------------------------------------------
# CHATBOT
# --------------------------------------------------

if "mensajes_chat" not in st.session_state:
    st.session_state.mensajes_chat = []


with tab_chatbot:
    with st.container(key="chatbot_shell"):
        st.markdown(
            """
            <style>
            .st-key-chatbot_shell {
                max-width: 920px;
                margin: 0 auto;
                padding: 1.25rem 1rem 1rem;
            }
            .st-key-chatbot_shell .chatbot-heading {
                display: flex;
                align-items: center;
                gap: .8rem;
                margin: .2rem 0 1.7rem;
            }
            .st-key-chatbot_shell .chatbot-mark {
                display: grid;
                place-items: center;
                width: 2.5rem;
                height: 2.5rem;
                border-radius: 50%;
                color: white;
                background: linear-gradient(145deg, #166534, #22a06b);
                font-size: 1.25rem;
            }
            .st-key-chatbot_shell .chatbot-title {
                margin: 0;
                font-size: 1.15rem;
                font-weight: 650;
                line-height: 1.25;
            }
            .st-key-chatbot_shell .chatbot-subtitle {
                margin: .2rem 0 0;
                color: #737373;
                font-size: .86rem;
            }
            .st-key-chatbot_shell .chatbot-welcome {
                max-width: 650px;
                margin: 5vh auto 2rem;
                text-align: center;
            }
            .st-key-chatbot_shell .chatbot-welcome h2 {
                margin-bottom: .55rem;
                font-size: clamp(1.8rem, 4vw, 2.35rem);
                font-weight: 650;
                letter-spacing: -.035em;
            }
            .st-key-chatbot_shell .chatbot-welcome p {
                color: #737373;
                font-size: 1rem;
            }
            .st-key-chatbot_shell [data-testid="stChatMessage"] {
                border-radius: 1.1rem;
                padding: .85rem 1.1rem;
                margin: .45rem 0 1rem;
            }
            .st-key-chatbot_shell [data-testid="stChatInput"] {
                position: fixed !important;
                left: 50%;
                bottom: 1rem;
                z-index: 1000;
                width: min(920px, calc(100vw - 2rem));
                transform: translateX(-50%);
                border-radius: 1.5rem;
                background: var(--background-color);
                box-shadow: 0 0 0 .75rem var(--background-color);
            }
            .st-key-chatbot_shell [data-testid="stChatInput"] textarea {
                padding-top: .85rem;
                padding-bottom: .85rem;
            }
            .st-key-chatbot_shell .stButton > button {
                border-radius: 1.2rem;
                text-align: left;
                white-space: normal;
                min-height: 2.7rem;
            }
            .st-key-chatbot_shell .chatbot-followups {
                margin-top: .8rem;
                color: #737373;
                font-size: .82rem;
            }
            @media (max-width: 700px) {
                .st-key-chatbot_shell { padding: .6rem .5rem 1rem; }
                .st-key-chatbot_shell .chatbot-welcome { margin-top: 3vh; }
            }
            </style>
            """,
            unsafe_allow_html=True,
        )

        if st.button("＋  Nueva conversación", key="chat_nueva_conversacion"):
            st.session_state.mensajes_chat = []
            st.session_state.pop("pregunta_sugerida_chat", None)
            for clave in list(st.session_state):
                if clave.startswith("mostrar_grafico_chat_"):
                    del st.session_state[clave]
            st.rerun()
        with st.container(height=390, border=False, key="chat_history"):
            pregunta_sugerida = None
            if not st.session_state.mensajes_chat:
                st.markdown(
                    """
                    <div class="chatbot-welcome">
                        <h2>¿Qué quieres explorar?</h2>
                        <p>Puedo ayudarte a encontrar tendencias y responder preguntas sobre tus exportaciones.</p>
                    </div>
                    """,
                    unsafe_allow_html=True,
                )
                columnas_inicio = st.columns(3)
                preguntas_inicio = [
                    "¿Qué país recibió más exportaciones?",
                    "Muéstrame la evolución mensual del FOB",
                    "¿Cuántos kilos se exportaron en total?",
                ]
                for posicion, (columna, sugerencia) in enumerate(
                    zip(columnas_inicio, preguntas_inicio)
                ):
                    with columna:
                        if st.button(
                            sugerencia,
                            key=f"chat_inicio_{posicion}",
                            use_container_width=True,
                        ):
                            pregunta_sugerida = sugerencia
            else:
                for indice, mensaje in enumerate(st.session_state.mensajes_chat):
                    with st.chat_message(mensaje["role"]):
                        texto_visible = limpiar_texto_analyst(
                            mensaje.get("content", "")
                        )
                        if texto_visible:
                            st.markdown(texto_visible)

                        if mensaje.get("resumen"):
                            st.markdown(mensaje["resumen"])

                        sugerencias = mensaje.get("sugerencias", [])
                        if sugerencias:
                            st.markdown(
                                '<div class="chatbot-followups">Puedes continuar con:</div>',
                                unsafe_allow_html=True,
                            )
                            columnas = st.columns(min(len(sugerencias), 3))
                            for posicion, (columna, sugerencia) in enumerate(
                                zip(columnas, sugerencias[:3])
                            ):
                                with columna:
                                    if st.button(
                                        sugerencia,
                                        key=f"chat_seguimiento_{indice}_{posicion}",
                                        use_container_width=True,
                                    ):
                                        pregunta_sugerida = sugerencia

                        if mensaje.get("sql"):
                            with st.expander("Ver SQL generado"):
                                st.code(mensaje["sql"], language="sql")

                        datos_mensaje = mensaje.get("datos")
                        if datos_mensaje is not None and mensaje["role"] == "assistant":
                            clave_grafico = f"mostrar_grafico_chat_{indice}"
                            if clave_grafico not in st.session_state:
                                st.session_state[clave_grafico] = False

                            texto_boton = (
                                "Ocultar gráfico"
                                if st.session_state[clave_grafico]
                                else "Ver gráfico"
                            )
                            if st.button(
                                texto_boton,
                                key=f"boton_grafico_chat_{indice}",
                            ):
                                st.session_state[clave_grafico] = not st.session_state[clave_grafico]
                                st.rerun()

                            if st.session_state[clave_grafico]:
                                figura = generar_grafico_chat(
                                    datos_mensaje,
                                    mensaje.get("pregunta", ""),
                                )
                                if figura is not None:
                                    st.plotly_chart(
                                        figura,
                                        width="stretch",
                                        key=f"grafico_historial_{indice}",
                                    )

        pregunta = st.chat_input(
            "Envía un mensaje sobre tus exportaciones…",
            key="chat_input_exportaciones",
        )
        if not pregunta:
            pregunta = pregunta_sugerida or st.session_state.pop(
                "pregunta_sugerida_chat", None
            )

        if pregunta:
            st.session_state.mensajes_chat.append({
                "role": "user",
                "content": pregunta,
            })

            try:
                with st.chat_message("assistant"):
                    with st.spinner("Analizando tus datos…"):
                        resultado = consultar_cortex(
                            pregunta,
                            st.session_state.mensajes_chat,
                        )

                texto = resultado["texto"]
                sql = resultado["sql"]
                datos = resultado["datos"]
                resumen = generar_resumen(datos, pregunta)
                st.session_state.mensajes_chat.append({
                    "role": "assistant",
                    "content": texto,
                    "resumen": resumen if datos is not None else None,
                    "sql": sql,
                    "datos": datos,
                    "pregunta": pregunta,
                    "contenido": resultado["contenido"],
                    "sugerencias": resultado["sugerencias"],
                })
                st.rerun()

            except Exception as error:
                mensaje_error = f"No pude completar esa consulta. Detalle: {error}"
                st.session_state.mensajes_chat.append({
                    "role": "assistant",
                    "content": mensaje_error,
                    "contenido": [{"type": "text", "text": mensaje_error}],
                })
                st.rerun()