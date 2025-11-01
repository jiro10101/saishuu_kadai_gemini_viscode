import logging
import re
from langchain_openai import ChatOpenAI
from langchain_core.prompts import ChatPromptTemplate
from langchain_core.output_parsers import StrOutputParser
from langchain_core.runnables import Runnable
from config import settings, TARGET_DEVICE, MAX_RUNTIME_SEC
import streamlit as st # @st.cache_resource のため

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

class LLMHandler:
    """
    LangChainとOpenAIモデルを管理し、
    「コマンド生成」と「質問応答」の2つの機能を提供するクラス。
    """
    
    def __init__(self):
        """
        LLMハンドラの初期化。
        APIキーのチェックと、LLMモデル、各チェーンの準備を行う。
        """
        logger.info("LLMHandler初期化開始")
        if not settings.OPENAI_API_KEY:
            logger.error("OPENAI_API_KEY が .env に設定されていません。")
            raise ValueError("OPENAI_API_KEY must be set.")
            
        logger.info("OpenAI APIキーの設定確認完了")
        # LLMモデルの定義
        self.llm = ChatOpenAI(
            # gpt-4o (推奨) または gpt-3.5-turbo など
            model="gpt-4o", 
            # .env から読み込んだキーを設定
            api_key=settings.OPENAI_API_KEY,
            # temperature (温度): 0.0に設定することで、LLMの応答の「ランダム性」を最小限にし、
            # 毎回ほぼ同じ、安全で予測可能なコマンドを生成させる (仕様書要件に適う)
            temperature=0.0 
        )
        logger.info("ChatOpenAIモデルの初期化完了")
        
        # 2種類のチェーン (処理の流れ) を定義
        # 1. コマンド生成専用チェーン
        logger.info("コマンド生成チェーンの作成開始")
        self.command_generator_chain = self._create_command_generator_chain()
        # 2. 一般的な質問応答用チェーン
        logger.info("QAチェーンの作成開始")
        self.qa_chain = self._create_qa_chain()
        logger.info("LLMHandler初期化完了")

    def _create_command_generator_chain(self) -> Runnable:
        """
        (仕様書要件) Linuxコマンド（特にfio）を生成するための
        LangChainチェーン（プロンプト + LLM + 出力パーサー）を作成する。
        
        [最重要] プロンプトに仕様書の制約を厳密に反映させることが、
        このアシスタントの安全性と機能性を担保します。
        """
        logger.info("コマンド生成チェーンの構築開始")
        
        # システムプロンプト (LLMの役割と制約を定義)
        system_prompt = f"""
あなたは Linux (Ubuntu 24.04) の専門家アシスタントです。
あなたの唯一の役割は、ユーザーの自然言語による指示を、指定された制約条件に厳密に従った単一のLinux bashコマンドに変換することです。

# 厳格なルール (LLMへの指示)
1.  **コマンドのみ**: 実行可能なbashコマンドのみを生成してください。
2.  **説明不要**: 説明、謝罪、挨拶、追加のテキスト（例: 「コマンドは以下の通りです」）は一切禁止します。
3.  **単一コマンド**: 1行のbashコマンドのみを返してください。

# 制約条件 (仕様書要件)
1.  **fioの制約 (最重要)**:
    * `fio` コマンドを生成する場合、対象デバイス (`--filename`) は必ず `{TARGET_DEVICE}` を使用してください。
    * `fio` の測定時間 (`--runtime`) は、必ず `{MAX_RUNTIME_SEC}` 秒 (つまり {MAX_RUNTIME_SEC}) 以下に設定してください。
    * `fio` を実行する際は、必ず `--name=test` `--filename={TARGET_DEVICE}` `--direct=1` `--time_based` `--runtime=[{MAX_RUNTIME_SEC}秒以下の数値]` を含めてください。
    * 読み取り/書き込みの指定がない場合は、安全な `--rw=read` (読み取り専用) を優先してください。
    * 例: `fio --name=test --filename={TARGET_DEVICE} --direct=1 --rw=randread --bs=4k --runtime=10 --time_based --group_reporting`

2.  **許可されるコマンド**:
    * `fio` (上記の制約内)
    * 状態確認コマンド: `ls`, `cat`, `df`, `free`, `top -n 1 b`, `iostat`, `vmstat`
    * `echo`

3.  **禁止コマンド (仕様書要件: セキュリティ)**:
    * システムの変更、ファイルの削除 (`rm`), ディレクトリの作成 (`mkdir`), 権限変更 (`chmod`, `chown`)。
    * パッケージ管理 (`apt`, `dpkg`)。
    * `reboot`, `shutdown`。
    * 外部へのネットワークアクセス (`curl`, `wget`, `ssh`, `scp`)。
    * `fio` 以外での `{TARGET_DEVICE}` への書き込み（例: `dd of={TARGET_DEVICE}`）。
    * 複数のコマンドの連結 (`;`, `&&`, `||`, `|` を使ったもの。ただし `top | ...` は許容範囲)。

# 違反時の対応
* 指示が制約に違反する場合（例: 「/etc/passwd を削除して」「100秒fioして」）。
* または、指示が曖昧でコマンドを生成できない場合。
* 上記の場合は、"Error: Request violates safety constraints or is unclear." という文字列のみを返してください。

# 出力例 (Few-shot learning: LLMに良い例と悪い例を示す)
User: /dev/nvme0n1 に4kブロックサイズでランダムリードのテストを5秒間実行して
You: fio --name=test --filename=/dev/nvme0n1 --direct=1 --rw=randread --bs=4k --runtime=5 --time_based --group_reporting

User: /dev/nvme0n1 のシーケンシャルライトを8kで10秒測定
You: fio --name=test --filename=/dev/nvme0n1 --direct=1 --rw=write --bs=8k --runtime=10 --time_based --group_reporting

User: ディスクの空き容量を見せて
You: df -h

User: /dev/sda をフォーマットして
You: Error: Request violates safety constraints or is unclear.

User: 30秒テストして (ランタイムが{MAX_RUNTIME_SEC}秒を超えている)
You: Error: Request violates safety constraints or is unclear.
"""
        
        # プロンプトテンプレートの作成
        prompt = ChatPromptTemplate.from_messages([
            ("system", system_prompt), # 上記のシステムプロンプト
            ("human", """Previous conversation:
{chat_history}

Current request: {query}""")      # ユーザーの入力を受け取るプレースホルダー
        ])
        
        # LangChain Expression Language (LCEL) を使用したチェーンの定義
        # (プロンプト) -> (LLMモデル) -> (文字列出力パーサー)
        logger.info("コマンド生成チェーンの構築完了")
        return prompt | self.llm | StrOutputParser()

    def _create_qa_chain(self) -> Runnable:
        """
        (仕様書要件) Ubuntu 24.04 に関する一般的な質問に回答するためのチェーン。
        こちらはコマンド生成とは異なり、通常の会話を行う。
        """
        logger.info("QAチェーンの構築開始")
        system_prompt = """
あなたは Ubuntu 24.04 に関する専門知識を持つ、親切なアシスタントです。
ユーザーの質問に対して、簡潔かつ正確に回答してください。
あなたはコマンドを実行する権限を持っていません。コマンド実行に関する指示は、別の担当（コマンド生成AI）が行うため、あなたは質問応答に専念してください。
"""
        prompt = ChatPromptTemplate.from_messages([
            ("system", system_prompt),
            ("human", """Previous conversation:
{chat_history}

Current question: {query}""")
        ])
        logger.info("QAチェーンの構築完了")
        return prompt | self.llm | StrOutputParser()

    def generate_bash_command(self, query: str, chat_history: list = None) -> str:
        """
        コマンド生成チェーンを実行し、自然言語クエリからbashコマンドを生成する。
        
        Args:
            query (str): ユーザーの現在の入力
            chat_history (list): 過去の会話履歴 [{"role": "user|assistant", "content": "..."}, ...]
        """
        logger.info(f"コマンド生成開始 - クエリ: {query}")
        if chat_history:
            logger.info(f"会話履歴も含めて処理 (履歴数: {len(chat_history)} 件)")
        try:
            # チェーンを実行 (LLMがプロンプトに従ってコマンド or エラーを返す)
            logger.info("LLMチェーンを実行中")
            # 会話履歴を含めてLLMに送信
            invoke_data = {"query": query, "chat_history": ""}
            if chat_history:
                invoke_data["chat_history"] = self._format_chat_history(chat_history)
            
            command = self.command_generator_chain.invoke(invoke_data)
            logger.info(f"LLMから生のコマンドを受信: '{command}'")
            logger.info(f"コマンドの型: {type(command)}, 長さ: {len(command) if command else 0}")
            
            # --- LLM出力のサニタイズ（念のため） ---
            # LLMがプロンプトの指示（説明不要）を破り、
            # 「`fio ...`」や「bash\nfio ...」のように余計なテキストを付加した場合に備える
            command = command.strip().strip("`")
            if command.startswith("bash\n"):
                command = command[5:].strip()
            logger.info(f"サニタイズ後のコマンド: '{command}'")
                
            # --- 二重検証 (仕様書要件: セキュリティ) ---
            # プロンプトで制約を与えても、LLMが制約を破る可能性はゼロではないため、
            # 生成されたコマンドをPythonコード側でも再度検証（バリデーション）する。
            logger.info("コマンドの安全性検証を開始")
            if self._validate_generated_command(command):
                # 検証OK
                logger.info(f"コマンド生成成功: {command}")
                return command
            else:
                # 検証NG
                logger.warning(f"LLMが生成したコマンドが安全検証に失敗しました: {command}")
                return "Error: Generated command violates safety constraints."
                
        except Exception as e:
            logger.error(f"コマンド生成 (LLM呼び出し) 中にエラー: {e}")
            return f"Error: Failed to invoke LLM. {e}"

    def _validate_generated_command(self, command: str) -> bool:
        """
        生成されたコマンドが制約（特にfio）を守っているか最終チェックする。
        (プロンプトによる指示の二重チェック)
        """
        logger.info(f"コマンド検証開始: {command}")
        # LLMが自らエラーを返した場合 (例: "Error: ...") は、安全なので許可
        if "Error:" in command:
            logger.info("LLMがエラーメッセージを返したため、検証OK")
            return True 

        command_lower = command.lower()

        # 1. ブラックリスト検証
        #    プロンプトで禁止しているが、念のため再チェック
        blacklist_patterns = ["rm ", "mkfs", "reboot", "shutdown", "wget ", "curl ", "ssh ", "apt ", "dd "]
        for pattern in blacklist_patterns:
            if pattern in command_lower:
                logger.warning(f"コマンド検証失敗: ブラックリストパターン '{pattern}' が含まれています。")
                return False

        # 2. fio の制約チェック
        if "fio" in command_lower:
            logger.info("fioコマンドの詳細検証を開始")
            # 2a. 対象デバイスの検証 (仕様書要件)
            if TARGET_DEVICE not in command:
                logger.warning(f"FIO検証失敗: 必須デバイス '{TARGET_DEVICE}' がコマンドに含まれていません。")
                return False
                
            # 2b. 実行時間の検証 (仕様書要件)
            # 正規表現で `--runtime=XX` の部分を抜き出す
            match = re.search(r"--runtime=(\d+)", command)
            if match:
                runtime = int(match.group(1))
                logger.info(f"fio実行時間チェック: {runtime}秒 (最大許容: {MAX_RUNTIME_SEC}秒)")
                if runtime > MAX_RUNTIME_SEC:
                    logger.warning(f"FIO検証失敗: 実行時間 {runtime}s が最大許容時間 {MAX_RUNTIME_SEC}s を超えています。")
                    return False
            else:
                # `--runtime` が指定されていない場合
                if "--time_based" in command_lower:
                     # --time_based があるのに --runtime がない場合、fioは停止しない可能性があるためブロック
                     logger.warning(f"FIO検証失敗: --time_based が指定されていますが --runtime がありません。")
                     return False
                     
        # すべての検証をパス
        logger.info("コマンド検証成功: すべてのチェックをパス")
        return True

    def _format_chat_history(self, chat_history: list) -> str:
        """
        チャット履歴をLLMが理解しやすい形式にフォーマットする。
        
        Args:
            chat_history (list): [{"role": "user|assistant", "content": "..."}, ...]
        
        Returns:
            str: フォーマットされた会話履歴文字列
        """
        if not chat_history:
            return ""
        
        formatted_history = []
        # 最新の5件の履歴のみを使用（トークン制限を考慮）
        recent_history = chat_history[-10:] if len(chat_history) > 10 else chat_history
        
        for message in recent_history:
            role = message.get("role", "")
            content = message.get("content", "")
            if role == "user":
                formatted_history.append(f"User: {content}")
            elif role == "assistant":
                formatted_history.append(f"Assistant: {content}")
        
        return "\n".join(formatted_history)

    def answer_question(self, query: str, chat_history: list = None) -> str:
        """
        QAチェーンを実行し、一般的な質問に回答する。
        
        Args:
            query (str): ユーザーの現在の入力
            chat_history (list): 過去の会話履歴 [{"role": "user|assistant", "content": "..."}, ...]
        """
        logger.info(f"QA応答開始 - クエリ: {query}")
        if chat_history:
            logger.info(f"会話履歴も含めて処理 (履歴数: {len(chat_history)} 件)")
        try:
            logger.info("QAチェーンを実行中")
            # 会話履歴を含めてLLMに送信
            invoke_data = {"query": query, "chat_history": ""}
            if chat_history:
                invoke_data["chat_history"] = self._format_chat_history(chat_history)
            
            answer = self.qa_chain.invoke(invoke_data)
            logger.info(f"QA応答完了 (長さ: {len(answer)} 文字)")
            return answer
        except Exception as e:
            logger.error(f"質問応答 (LLM呼び出し) 中にエラー: {e}")
            return f"Error: Failed to invoke LLM. {e}"

# --- Streamlitのキャッシュ機能 ---
# @st.cache_resource デコレータを使うことで、Streamlitがリロードされるたびに
# LLMHandler (と内部のLLMモデル) を再初期化するのを防ぎ、高速化とコスト削減を図ります。
@st.cache_resource
def get_llm_handler():
    """
    LLMHandlerのシングルトンインスタンスを取得する。
    """
    logger.info("get_llm_handler() 呼び出し")
    try:
        handler = LLMHandler()
        logger.info("LLMHandlerインスタンス作成成功")
        return handler
    except ValueError as e:
        # (例: OpenAI APIキーがない場合)
        logger.error(f"LLMハンドラの初期化に失敗しました: {e}")
        st.error(f"LLMハンドラの初期化に失敗: {e}. 'frontend/.env' ファイルに OPENAI_API_KEY が設定されているか確認してください。")
        return None
    