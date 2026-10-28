import snowflake.connector
import streamlit as st
from cryptography.hazmat.primitives import serialization


def conectar():
    cfg = st.secrets["snowflake"]

    clave = serialization.load_pem_private_key(
        cfg["private_key"].encode(),
        password=None,
    )
    clave_der = clave.private_bytes(
        encoding=serialization.Encoding.DER,
        format=serialization.PrivateFormat.PKCS8,
        encryption_algorithm=serialization.NoEncryption(),
    )

    return snowflake.connector.connect(
        account=cfg["account"],
        user=cfg["user"],
        private_key=clave_der,
        warehouse=cfg["warehouse"],
        role=cfg.get("role"),
        database="SOURCE_DATA",
        schema="PUBLIC",
    )