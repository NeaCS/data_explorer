# Publicar la aplicación

La aplicación usa Streamlit y autentica contra Snowflake con una llave privada. El mismo bloque de configuración sirve en el equipo local y en un servicio de hosting.

## 1. Prepara las credenciales de Snowflake

1. Registra la llave pública correspondiente a `rsa_key.p8` en el usuario de Snowflake configurado para la app. La llave privada debe permanecer secreta.
2. Comprueba que ese usuario tenga acceso al warehouse, al rol, a `SOURCE_DATA.PUBLIC` y a la vista semántica usada por la aplicación.
3. En `.streamlit/secrets.toml` local, configura `[snowflake]` con `account`, `user`, `warehouse`, `role` y `private_key`. Usa el contenido PEM de la llave privada como cadena multilínea TOML entre comillas triples.

No subas `.streamlit/secrets.toml`, `rsa_key.p8` ni ninguna copia de la llave privada al repositorio. El `.gitignore` los excluye.

## 2. Publica el código

Sube `app.py`, `conexion.py` y `requirements.txt` a un repositorio Git. En Streamlit Community Cloud, crea una aplicación desde ese repositorio y selecciona `app.py` como archivo principal. El hosting instalará las dependencias declaradas en `requirements.txt`.

En la configuración de la aplicación alojada, añade el mismo bloque TOML `[snowflake]` en Secrets. No pegues las credenciales en el código ni en archivos versionados.

## 3. Valida la conexión alojada

Abre la URL publicada y ejecuta una consulta desde la app. Si falla, revisa los logs del hosting:

- Un error de `st.secrets` suele indicar que falta una clave o que el bloque TOML no está bien formado.
- Un error de llave pública suele indicar que la clave pública registrada en Snowflake no corresponde a la privada configurada en Secrets.
- Un error de permisos suele indicar que faltan privilegios sobre el warehouse, la base, el esquema o la vista semántica.
- Un error de conexión o timeout puede indicar una política de red de Snowflake que no permite el tráfico de salida del hosting.

El archivo principal es `app.py`. La configuración de Snowflake está centralizada en `conexion.py` y no contiene credenciales fijas.
