import streamlit as st
import requests
import logging
from .config import settings, SSH_TARGET_HOST
from .llm_handler import get_llm_handler # キャッシュされたハンドラを取得

# ロガー設定
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

# Streamlitページの基本設定
st.set_page_config(page_title="Linux Assistant", layout="wide")

# --- セッションステートの初期化 ---
# Streamlitはスクリプトを上から下に実行するため、
# ボタンクリックなどで値がリセットされないよう、st.session_state に値を保持します。

# "messages": チャットの会話履歴を保持するリスト
if "messages" not in st.session_state:
    st.session_state.messages = []

# "command_to_confirm": (仕様書要件) 実行確認待ちのコマンドを保持
if "command_to_confirm" not in st.session_state:
    st.session_state.command_to_confirm = None

# "original_query": 確認待ちコマンドの「元のクエリ」 (FastAPIでの保存用)
if "original_query" not in st.session_state:
    st.session_state.original_query = None

def main():
    """
    Streamlit UIのメイン関数 (エントリーポイント)
    """
    st.title(f"🤖 Linux アシスタント (Ubuntu 24.04)")
    st.caption(f"SSH接続先ホスト: **{SSH_TARGET_HOST}**")
    
    # --- LLMハンドラの初期化 ---
    llm_handler = get_llm_handler()
    if not llm_handler:
        # llm_handler.py でAPIキーがない場合などにNoneが返る
        st.error(f"LLMハンドラの読み込みに失敗しました。`frontend/.env` の設定を確認してください。")
        st.stop() # エラー時はアプリを停止
        
    # --- チャット履歴の表示 ---
    # st.session_state.messages に保存されている履歴をすべて描画する
    for message in st.session_state.messages:
        with st.chat_message(message["role"]): # "user" または "assistant"
            st.markdown(message["content"])

    # --- UIの分岐ロジック ---
    
    # (A) 実行確認待ちのコマンドがある場合 (仕様書要件: 実行前確認)
    if st.session_state.command_to_confirm:
        # 確認用のUI (実行/破棄ボタン) を表示
        display_confirmation_ui(st.session_state.command_to_confirm)
        # 確認中は、下のチャット入力を無効化する
        st.chat_input(disabled=True)
        
    # (B) 通常時 (確認待ちコマンドがない場合)
    else:
        # ユーザーからの新規入力を受け付けるチャット入力ボックス
        query = st.chat_input("Ubuntu 24.04 に関する質問、または 'fio' 操作指示を入力...")
        
        if query:
            # 1. ユーザーの入力を履歴に追加・表示
            st.session_state.messages.append({"role": "user", "content": query})
            with st.chat_message("user"):
                st.markdown(query)
                
            # 2. アシスタントの応答処理
            with st.chat_message("assistant"):
                with st.spinner("思考中..."):
                    # 2a. まず、コマンド生成を試みる
                    generated_command = llm_handler.generate_bash_command(query)
                
                # 2b. コマンド生成が成功したか判定
                if generated_command and not generated_command.startswith("Error:"):
                    # 成功した場合 (例: "fio ...")
                    # -> 実行確認ステートに移行
                    logger.info(f"コマンド生成成功: {generated_command}")
                    st.session_state.command_to_confirm = generated_command
                    st.session_state.original_query = query # 保存用
                    
                    # StreamlitにUIを再描画させ、(A)の確認UIを表示させる
                    st.rerun() 
                    
                else:
                    # 失敗した場合 (例: "Error: ..." または コマンドではないと判断された)
                    logger.info(f"コマンド生成失敗または対象外 ({generated_command})。QAモードにフォールバックします。")
                    
                    # 2c. QA (質問応答) モードにフォールバック
                    with st.spinner("質問に回答中..."):
                        answer = llm_handler.answer_question(query)
                    
                    # 回答を表示・履歴に追加
                    st.markdown(answer)
                    st.session_state.messages.append({"role": "assistant", "content": answer})

def display_confirmation_ui(command: str):
    """
    (仕様書要件) コマンド実行の最終確認UIを表示する。
    
    Args:
        command (str): LLMが生成した実行対象のコマンド。
    """
    st.warning(f"以下のコマンドが生成されました。**{SSH_TARGET_HOST}** で実行しますか？")
    
    # 実行されるコマンドをコードブロックで明示
    st.code(command, language="bash")
    
    col1, col2 = st.columns([1, 1])
    with col1:
        # 「実行」ボタン
        if st.button("✅ 実行する (Execute)", key="confirm_execute", use_container_width=True, type="primary"):
            logger.info(f"ユーザーがコマンド実行を承認: {command}")
            # FastAPIバックエンドにリクエストを送信
            execute_command(command, st.session_state.original_query)
            
            # 処理完了後、確認ステートを解除 (通常モードに戻る)
            st.session_state.command_to_confirm = None
            st.session_state.original_query = None
            st.rerun() # UIを更新して結果を表示

    with col2:
        # 「破棄」ボタン
        if st.button("❌ 破棄する (Cancel)", key="cancel_execute", use_container_width=True):
            logger.info(f"ユーザーがコマンド実行をキャンセル: {command}")
            # 破棄した旨をチャット履歴に追加
            cancel_message = f"コマンド実行をキャンセルしました:\n```bash\n{command}\n```"
            st.session_state.messages.append({"role": "assistant", "content": cancel_message})
            
            # 確認ステートを解除 (通常モードに戻る)
            st.session_state.command_to_confirm = None
            st.session_state.original_query = None
            st.rerun() # UIを更新


def execute_command(command: str, query: str | None):
    """
    FastAPIバックエンドの /execute エンドポイントにHTTP POSTリクエストを送信する。
    
    Args:
        command (str): 実行するコマンド。
        query (str | None): 保存用の元のクエリ。
    """
    # configからFastAPIのURLを取得
    api_url = f"{settings.FASTAPI_BACKEND_URL}/execute"
    # FastAPIのCommandRequestモデルに合わせたペイロード
    payload = {"command": command, "query": query}
    
    # 実行中のステータスを表示するためのプレースホルダー
    status_placeholder = st.empty()
    
    try:
        with st.spinner(f"コマンド実行中... (バックエンドAPI: {api_url} に接続中)"):
            # requestsライブラリを使ってFastAPIにPOSTリクエストを送信
            # fio実行は10秒以上かかるため、タイムアウトを長め(120秒)に設定
            response = requests.post(api_url, json=payload, timeout=120) 
            
        # 1. バックエンドからの応答が正常 (HTTP 200) の場合
        if response.status_code == 200:
            data = response.json() # CommandResponse モデルに対応
            stdout = data.get("stdout")
            stderr = data.get("stderr")
            exit_code = data.get("exit_code")
            saved_path = data.get("saved_path") # リモート保存先
            
            status_placeholder.success(f"コマンド実行完了 (終了コード: {exit_code})")
            
            # --- 結果をチャット履歴に追加 ---
            result_content = f"コマンドを実行しました: `{command}`\n\n"
            
            # (仕様書要件) 保存先の表示
            if saved_path:
                result_content += f"**結果保存先 (リモート):** `{saved_path}`\n\n"
            else:
                result_content += "**警告:** リモートへの結果保存に失敗しました。(バックエンドログを確認してください)\n\n"

            # stdout / stderr があれば表示
            if stdout:
                result_content += f"### 標準出力 (stdout)\n```text\n{stdout}\n```\n"
            if stderr:
                result_content += f"### 標準エラー (stderr)\n```text\n{stderr}\n```\n"

            st.session_state.messages.append({"role": "assistant", "content": result_content})

        # 2. バックエンドがエラー (HTTP 4xx, 5xx) を返した場合
        else:
            status_placeholder.error(f"FastAPIバックエンドへのリクエストに失敗しました (Status: {response.status_code})")
            try:
                # FastAPIが返した詳細なエラーメッセージ (例: "SSH接続に失敗...") を取得
                error_detail = response.json().get("detail", response.text)
            except requests.exceptions.JSONDecodeError:
                error_detail = response.text
                
            logger.error(f"FastAPI エラー (Status {response.status_code}): {error_detail}")
            st.session_state.messages.append({"role": "assistant", "content": f"実行エラー (Backend):\n```\n{error_detail}\n```"})

    # 3. HTTPリクエスト自体の例外処理
    except requests.exceptions.ConnectionError:
        err_msg = f"FastAPIバックエンド ({api_url}) に接続できません。バックエンドサーバが起動しているか、ネットワーク接続を確認してください。"
        status_placeholder.error(err_msg)
        st.session_state.messages.append({"role": "assistant", "content": f"接続エラー: {err_msg}"})
    except requests.exceptions.Timeout:
        err_msg = f"FastAPIバックエンドへの接続がタイムアウトしました (120秒)。fioの実行が時間内に終わらなかったか、サーバの応答がありません。"
        status_placeholder.error(err_msg)
        st.session_state.messages.append({"role": "assistant", "content": f"タイムアウトエラー: {err_msg}"})
    except requests.exceptions.RequestException as e:
        # その他の requests に関するエラー
        logger.error(f"リクエスト例外: {e}")
        status_placeholder.error(f"リクエスト中にエラーが発生しました: {e}")
        st.session_state.messages.append({"role": "assistant", "content": f"リクエストエラー: {e}"})


if __name__ == "__main__":
    main()
