
import streamlit as st
import pandas as pd
import plotly.express as px
import requests

from conexion import conectar


# --------------------------------------------------
# CONFIGURACIÓN
# --------------------------------------------------

st.set_page_config(
    page_title="Dashboard de Exportaciones",
    page_icon="📊",
    layout="wide",
)

SEMANTIC_VIEW = "SOURCE_DATA.PUBLIC.SOURCE_DATA_SV"
API_ENDPOINT = "/api/v2/cortex/analyst/message"

st.title("Dashboard de Exportaciones")


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
# RESUMEN AUTOMÁTICO EN PALABRAS
# --------------------------------------------------

def generar_resumen(datos, pregunta):
    if datos is None or datos.empty:
        return "La consulta no devolvió resultados para analizar."

    df = datos.copy()
    df.columns = df.columns.str.upper()
    pregunta_lower = pregunta.lower()

    palabras_kilos = ["kilos", "kg", "cantidad", "volumen"]
    palabras_precio = [
        "precio promedio", "precio por kilo", "precio por kg"
    ]
    palabras_fob = ["fob", "valor", "ventas", "ingresos"]

    if any(p in pregunta_lower for p in palabras_precio):
        preferencias = ["PRECIO PROMEDIO", "PRECIO USD"]
        unidad = "US$ por kg"
    elif any(p in pregunta_lower for p in palabras_kilos):
        preferencias = ["TOTAL KG", "CANTIDAD", "KILOS"]
        unidad = "kg"
    elif any(p in pregunta_lower for p in palabras_fob):
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
            "porcentaje", "proporción", "proporcion",
            "participación", "participacion"
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

    # Resultado único, incluyendo su categoría.
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
# GENERACIÓN AUTOMÁTICA DE GRÁFICOS
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
                "total fob", "valor fob", "fob",
                "total kg", "cantidad", "kilos",
                "precio promedio", "precio usd",
                "total", "valor", "porcentaje"
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
            "evolución", "evolucion", "tendencia",
            "histórico", "historico", "mensual",
            "por mes", "por año", "anual",
            "a través del tiempo", "con el tiempo"
        ]
    )

    if temporal and pide_evolucion:
        df = df.dropna(subset=[temporal, valor]).sort_values(temporal)

        if df.empty:
            return None

        fig = px.line(
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

        return preparar_grafico(fig)

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
            "porcentaje", "proporción", "proporcion",
            "participación", "participacion",
            "distribución", "distribucion"
        ]
    )

    if pide_proporcion and 2 <= len(df) <= 10:
        df = df.dropna(subset=[categoria, valor])

        if df.empty:
            return None

        fig = px.pie(
            df,
            names=categoria,
            values=valor,
            hole=0.35,
            title=f"Distribución de {normalizar(valor)}",
        )

        return preparar_grafico(fig)

    df[valor] = pd.to_numeric(df[valor], errors="coerce")
    df = df.dropna(subset=[categoria, valor]).sort_values(
        valor,
        ascending=True,
    )

    if df.empty:
        return None

    fig = px.bar(
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
        fig,
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
# CORTEX ANALYST
# --------------------------------------------------

def consultar_cortex(pregunta, historial=None):
    conn = conectar()

    try:
        url = f"https://{conn.host}{API_ENDPOINT}"

        # Cada consulta se envía sin historial previo para diagnosticar
        # el error HTTP 400 de las preguntas consecutivas.
        respuesta = requests.post(
            url,
            headers={
                "Authorization": f'Snowflake Token="{conn.rest.token}"',
                "Content-Type": "application/json",
            },
            json={
                "semantic_view": SEMANTIC_VIEW,
                "messages": [
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

        if not respuesta.ok:
            print("ESTADO HTTP:", respuesta.status_code)
            print("DETALLE CORTEX:", respuesta.text)

            try:
                detalle = respuesta.json()
            except ValueError:
                detalle = respuesta.text

            raise RuntimeError(
                f"Snowflake respondió HTTP {respuesta.status_code}: "
                f"{detalle}"
            )

        resultado = respuesta.json()
        mensaje = resultado.get("message", {})
        contenido = mensaje.get("content", [])

        textos = []
        sql = None

        for bloque in contenido:
            if bloque.get("type") == "text":
                textos.append(bloque.get("text", ""))

            elif bloque.get("type") == "sql":
                sql = bloque.get("statement")

        datos = None

        if sql:
            sql_limpio = sql.strip().rstrip(";")
            sql_mayusculas = sql_limpio.upper()

            if (
                not sql_mayusculas.startswith("SELECT")
                or "SEMANTIC_VIEW(" not in sql_mayusculas
                or ";" in sql_limpio
            ):
                raise ValueError(
                    "La consulta generada no pasó "
                    "la validación básica de lectura."
                )

            cursor = conn.cursor()

            try:
                cursor.execute(sql_limpio)
                columnas = [
                    columna[0] for columna in cursor.description
                ]
                datos = pd.DataFrame(
                    cursor.fetchall(),
                    columns=columnas,
                )
            finally:
                cursor.close()

        texto = "\n\n".join(
            item for item in textos if item
        ).strip()

        if not texto:
            texto = (
                "Cortex Analyst generó una consulta SQL."
                if sql
                else "Cortex Analyst no devolvió una respuesta."
            )

        return {
            "texto": texto,
            "sql": sql,
            "datos": datos,
            "contenido": contenido,
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
                paises["TOTAL_FOB_USD"], errors="coerce"
            ).fillna(0)

            fig = px.bar(
                paises.sort_values("TOTAL_FOB_USD"),
                x="TOTAL_FOB_USD",
                y="PAIS_DESTINO",
                orientation="h",
                labels={
                    "TOTAL_FOB_USD": "Valor FOB (USD)",
                    "PAIS_DESTINO": "País de destino",
                },
            )
            st.plotly_chart(preparar_grafico(fig, 450), width="stretch")
        else:
            st.info("No hay datos por país.")

        col1, col2 = st.columns(2)

        with col1:
            st.subheader("Valor FOB por fruta")

            if not frutas.empty:
                frutas["TOTAL_FOB_USD"] = pd.to_numeric(
                    frutas["TOTAL_FOB_USD"], errors="coerce"
                ).fillna(0)

                fig = px.pie(
                    frutas,
                    names="FRUTA",
                    values="TOTAL_FOB_USD",
                    hole=0.4,
                )
                st.plotly_chart(preparar_grafico(fig), width="stretch")
            else:
                st.info("No hay datos por fruta.")

        with col2:
            st.subheader("Evolución mensual del valor FOB")

            if not meses.empty:
                meses["MES"] = pd.to_datetime(meses["MES"], errors="coerce")
                meses["TOTAL_FOB_USD"] = pd.to_numeric(
                    meses["TOTAL_FOB_USD"], errors="coerce"
                ).fillna(0)
                meses = meses.dropna(subset=["MES"])

                fig = px.line(
                    meses.sort_values("MES"),
                    x="MES",
                    y="TOTAL_FOB_USD",
                    markers=True,
                    labels={
                        "MES": "Mes",
                        "TOTAL_FOB_USD": "Valor FOB (USD)",
                    },
                )
                st.plotly_chart(preparar_grafico(fig), width="stretch")
            else:
                st.info("No hay datos mensuales.")

        st.subheader("Cantidad exportada por fruta")

        if not frutas.empty:
            frutas["TOTAL_KG"] = pd.to_numeric(
                frutas["TOTAL_KG"], errors="coerce"
            ).fillna(0)

            fig = px.bar(
                frutas.sort_values("TOTAL_KG"),
                x="TOTAL_KG",
                y="FRUTA",
                orientation="h",
                labels={
                    "TOTAL_KG": "Cantidad (kg)",
                    "FRUTA": "Fruta",
                },
            )
            st.plotly_chart(preparar_grafico(fig), width="stretch")

        st.subheader("Valor FOB por exportadora")

        if not exportadoras.empty:
            exportadoras["TOTAL_FOB_USD"] = pd.to_numeric(
                exportadoras["TOTAL_FOB_USD"], errors="coerce"
            ).fillna(0)

            fig = px.treemap(
                exportadoras,
                path=["EXPORTADORA"],
                values="TOTAL_FOB_USD",
            )
            st.plotly_chart(preparar_grafico(fig, 420), width="stretch")

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
    st.subheader("Consulta tus exportaciones")
    st.write("Haz preguntas en lenguaje natural sobre los datos de Snowflake.")

    # Mostrar el historial visual del chat.
    for indice, mensaje in enumerate(st.session_state.mensajes_chat):
        with st.chat_message(mensaje["role"]):
            st.markdown(mensaje["content"])

            if mensaje.get("resumen"):
                st.markdown("**Resumen de los resultados**")
                st.markdown(mensaje["resumen"])

            if mensaje.get("sql"):
                with st.expander("Ver SQL generado"):
                    st.code(mensaje["sql"], language="sql")

            datos_mensaje = mensaje.get("datos")

            if datos_mensaje is not None:
                st.dataframe(datos_mensaje, width="stretch")

                if mensaje["role"] == "assistant":
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
        "Ej.: ¿Qué país tiene el mayor valor FOB?"
    )

    if pregunta:
        st.session_state.mensajes_chat.append({
            "role": "user",
            "content": pregunta,
        })

        with st.chat_message("user"):
            st.markdown(pregunta)

        try:
            with st.spinner("Consultando Cortex Analyst..."):
                # La consulta se envía sin historial.
                resultado = consultar_cortex(pregunta, [])

            texto = resultado["texto"]
            sql = resultado["sql"]
            datos = resultado["datos"]
            resumen = generar_resumen(datos, pregunta)

            with st.chat_message("assistant"):
                st.markdown(texto)

                if datos is not None:
                    st.markdown("**Resumen de los resultados**")
                    st.markdown(resumen)

                if sql:
                    with st.expander("Ver SQL generado"):
                        st.code(sql, language="sql")

                if datos is not None:
                    st.dataframe(datos, width="stretch")

                    figura = generar_grafico_chat(datos, pregunta)

                    if figura is not None:
                        st.plotly_chart(
                            figura,
                            width="stretch",
                            key=f"grafico_nuevo_{len(st.session_state.mensajes_chat)}",
                        )

            st.session_state.mensajes_chat.append({
                "role": "assistant",
                "content": texto,
                "resumen": resumen if datos is not None else None,
                "sql": sql,
                "datos": datos,
                "pregunta": pregunta,
            })

        except Exception as error:
            st.error(f"Error al consultar Cortex Analyst: {error}")

    if st.button("Limpiar conversación"):
        st.session_state.mensajes_chat = []
        st.rerun()