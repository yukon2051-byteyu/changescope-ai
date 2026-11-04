# Hugging Face Spaces（Docker 方式）で ChangeScope AI を動かすための設定。
# 秘密情報（ANTHROPIC_API_KEY・ACCESS_CODES・USAGE_DATABASE_URL）はここに書かず、Space の Settings の Secrets に登録する
# （実行時に環境変数として渡される）。
FROM python:3.12-slim

# Hugging Face Spaces はユーザー番号 1000 で動かすため、そのユーザーを作って使う（ファイルの権限の問題を防ぐ）
RUN useradd -m -u 1000 user
USER user
ENV HOME=/home/user \
    PATH=/home/user/.local/bin:$PATH \
    PYTHONUTF8=1
WORKDIR $HOME/app

# ライブラリを先に入れる（コードだけ変えたときは、この段を作り直さずに済む）
COPY --chown=user requirements.txt .
RUN pip install --no-cache-dir --upgrade pip && pip install --no-cache-dir -r requirements.txt

COPY --chown=user . .

# README の app_port（8501）と合わせる。
# 中継サーバーを通るため、ファイルの読み込み（Excelのアップロード）が拒否されないよう、XSRF と CORS の確認を外す
EXPOSE 8501
CMD ["streamlit", "run", "app.py", "--server.port=8501", "--server.address=0.0.0.0", "--server.headless=true", \
     "--server.enableXsrfProtection=false", "--server.enableCORS=false"]
