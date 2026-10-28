cuerpo = "".join(
    linea.strip()
    for linea in open("rsa_key.pub")
    if "-----" not in linea
)
print(f"ALTER USER \"nea.castroserrano\" SET RSA_PUBLIC_KEY='{cuerpo}';")