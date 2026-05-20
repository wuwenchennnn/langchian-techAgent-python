import base64
import sys


def encrypt_value(plain_text: str, secret_key: str) -> str:
    plain_bytes = plain_text.encode("utf-8")
    key_bytes = secret_key.encode("utf-8")
    cipher_bytes = bytes(
        byte ^ key_bytes[index % len(key_bytes)]
        for index, byte in enumerate(plain_bytes)
    )
    return base64.b64encode(cipher_bytes).decode("utf-8")


if __name__ == "__main__":
    if len(sys.argv) != 3:
        print("usage: python encrypt_config.py <plain_text> <secret_key>")
        raise SystemExit(1)

    print(encrypt_value(sys.argv[1], sys.argv[2]))
