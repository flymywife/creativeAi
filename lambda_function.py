import json
import logging
import openai
import os
import sys
import boto3
import lambda_dao

from datetime import datetime
from zoneinfo import ZoneInfo
from linebot import LineBotApi, WebhookHandler
from linebot.exceptions import InvalidSignatureError, LineBotApiError
from linebot.models import MessageEvent, TextMessage, TextSendMessage

# INFOレベル以上のログメッセージを拾うように設定
logger = logging.getLogger()
logger.setLevel(logging.INFO)

# 環境変数からチャネルアクセストークンキー取得
CHANNEL_ACCESS_TOKEN = os.getenv('CHANNEL_ACCESS_TOKEN')
# 環境変数からチャネルシークレットキーを取得
CHANNEL_SECRET = os.getenv('CHANNEL_SECRET')

# 環境変数からOpenAI APIのシークレットキーを取得
openai.api_key = os.getenv('SECRET_KEY')


# それぞれ環境変数に登録されていないとエラー
if CHANNEL_ACCESS_TOKEN is None:
    logger.error(
        'LINE_CHANNEL_ACCESS_TOKEN is not defined as environmental variables.')
    sys.exit(1)
if CHANNEL_SECRET is None:
    logger.error(
        'LINE_CHANNEL_SECRET is not defined as environmental variables.')
    sys.exit(1)
if openai.api_key is None:
    logger.error(
        'Open API key is not defined as environmental variables.')
    sys.exit(1)

line_bot_api = LineBotApi(CHANNEL_ACCESS_TOKEN)
webhook_handler = WebhookHandler(CHANNEL_SECRET)

# ユーザーからのメッセージを処理する
@webhook_handler.add(MessageEvent, message=TextMessage)
def handle_message(event):
    # eventからsourceを取得
    source = event.source
    # sourceからuserIdを取得
    user_id = source.user_id
    # ユーザーからのメッセージ
    query = event.message.text

    instructions = (
        '献立ボット「クッキングママローラ」は'
        'お料理の献立を考えてくれるボットです😊\n'
        '【機能】\n'
        '自己紹介でお名前を言っていただければ、ローラママはあなたの名前を憶えてくれます。\n'
        '嫌いな食べ物を最初に教えてください。複数ある場合はいっぺんに伝えて。ローラママはあなたの嫌いな食べ物を覚えてくれます。\n'
        '「献立考えて」というと献立を考えてくれます。\n'
        'ローラママが提案した献立を採用する場合「採用」と言いましょう。\n'
        '採用した献立はローラママが覚えていてくれます。👍\n'
        '採用した献立はあとで呼び出すことが出来ます。日付指定も出来るので試してみてください。\n'
        '利用制限回数は12回です。毎日0時に回数がリセットされます。'
        '説明書以外の発言は利用回数がカウントされます。'
        )
    if query[:3] == "説明書":
        return line_bot_api.reply_message(event.reply_token, TextSendMessage(text=instructions))
        
    # user情報を取得
    get_user = lambda_dao.get_user_info(user_id)
    # user_idが存在しない場合新しく登録
    if get_user is None:
        now_obj = datetime.now(ZoneInfo("Asia/Tokyo"))
        now = now_obj.isoformat()
        user_name = 'ななし'
        hate_food = 'わかりません'
        # 登録するアイテム情報
        user_item = {
            'user_id': user_id,
            'limit': 0,
            'mail': None,
            'registration_date': now,
            'update_date': now,
            'user_name':  user_name,
            'hate_food': hate_food
            }
        lambda_dao.put_user_info(user_item)
        
    # 利用制限回数カウントアップ
    limit = lambda_dao.increment_limit(user_id)
    if limit is None:
        return line_bot_api.reply_message(event.reply_token, TextSendMessage(text='おや？ユーザー情報が見つからないよ？もう一度試してみてね。'))  
    elif limit >= 12:
         limit_message = (
        '利用制限に達したよ！'
        '毎日0時に制限がリセットされるよ！'
         )
         return line_bot_api.reply_message(event.reply_token, TextSendMessage(text=limit_message))   

    # ユーザー名
    if get_user is not None:
        user_name = get_user['user_name']
        # 嫌いな食べ物
        hate_food = get_user['hate_food']
    # 会話過去履歴を取得
    get_talk = lambda_dao.get_talk_history(user_id, 5)
    # 会話履歴5件分の入れ物
    past_messages = [''] * 5
    past_replies = [''] * 5
    
    # 会話履歴5件分を入れ物に1個1個入れていく
    for i in range(min(5, len(get_talk['Items']))):
        past_messages[i] = get_talk['Items'][i]['message']
        past_replies[i] = get_talk['Items'][i]['reply']
    
    # 会話履歴を個別に詰め替える
    past_message5, past_message4, past_message3, past_message2, past_message1 = past_messages
    past_reply5, past_reply4, past_reply3, past_reply2, past_reply1 = past_replies
    now_obj = datetime.now(ZoneInfo("Asia/Tokyo"))
    now = now_obj.isoformat()
    # プロンプト
    messages=[
            {'role': 'system', 'content': 'あなたは献立を考えるクッキングママローラです。'
            'あなたはフランスリヨン出身の48歳専業主婦です。趣味でユーザーの献立を考えるクッキングママをしています。'
            'あなたはどんな料理でも作れます。家庭料理が最も得意です。'
            '一人称は「あたし」か「ローラママ」でお願いします。'
            '「だわ」とか「わよ」とか女性っぽい喋り方を心がけてください'
             f'現在日時は{now}です。現在日時が必要な時に利用してください。'
             f'ユーザーの名前は{user_name}です。' 
             f'ユーザーの嫌いな食べ物は{hate_food}' 
             'ユーザーから「献立考えて」と言われたら必ず何か献立を提案してください' 
             '献立は一度にいくつも提案しないでください。１つに絞ってください。'
             'ユーザーの嫌いな食べ物は献立に入れないでください '
            },
            {'role': 'user', 'content': f'{past_message1}'},
            {'role': 'assistant', 'content': f'{past_reply1}'},
            {'role': 'user', 'content': f'{past_message2}'},
            {'role': 'assistant', 'content': f'{past_reply2}'},
            {'role': 'user', 'content': f'{past_message3}'},
            {'role': 'assistant', 'content': f'{past_reply3}'},
            {'role': 'user', 'content': f'{past_message4}'},
            {'role': 'assistant', 'content': f'{past_reply4}'},
            {'role': 'user', 'content': f'{past_message5}'},
            {'role': 'assistant', 'content': f'{past_reply5}'},
            {'role': 'user', 'content': query}
        ]
    functions=[
            {
                "name": "update_user_name",
                "description": """ユーザー名の保存""",
                "parameters": {
                    "type": "object",
                    "properties": {
                        "user_name": {
                            "type": "string",
                            "description": "ユーザーの名前。自己紹介されたら名前を保存する。"
                        },
                    }
                },
                "required": ["user_name"]
            },
            {
                "name": "update_hate_food",
                "description": """ユーザーの嫌いな食べ物・苦手な食べ物を保存""",
                "parameters": {
                    "type": "object",
                    "properties": {
                        "hate_food": {
                            "type": "string",
                            "description": "ユーザーの嫌いな食べ物・苦手な食べ物。複数ある場合は、区切りで保存する"
                        },
                    }
                },
                "required": ["hate_food"]
            },
            {
                "name": "update_recipi",
                "description": """自分の提案した献立が「採用」と言われたら採用された献立を保存
                （料理名を記載、もしメインディッシュサイドディッシュデザートなどがある場合全て保存）""",
                "parameters": {
                    "type": "object",
                    "properties": {
                        "recipi": {
                            "type": "string",
                            "description": "ユーザーに提案した献立"
                        },
                    }
                },
                "required": ["recipi"]
            },
            {
                "name": "get_past_recipi",
                "description": "今までの提案した献立を参照する必要があるときに過去の献立を参照する",
                "parameters": {
                    "type": "object",
                    "properties":{
                        "start_date": {
                            "type": "string",
                            "description": "参照する過去献立の範囲の開始日付。指定する形式はyyyy-mm-ddT00:00:00.000000+09:00。指定がない場合現在日時からみて3日前で良い。"
                        },
                        "end_date": {
                            "type": "string",
                            "description": "参照する過去献立の範囲の終了日付。指定する形式はyyyy-mm-ddT23:59:59.999999+09:00。指定がない場合現在日時からみて昨日で良い。"
                        },
                    }
                }, 
                "required": ["start_date", "end_date"],
            }
        ]

     # ChatGPTに質問を投げて回答を取得する
    answer_response = call_gpt(messages, functions)
    
    answer = answer_response["choices"][0]["message"]["content"]
    message = answer_response["choices"][0]["message"]
    
    # 受け取った回答のJSONを目視確認できるようにINFOでログに吐く
    logger.info(answer_response)
    
    # STEP2: モデルが関数を呼び出したいかどうかを確認
    if message.get("function_call"):
        function_name = message["function_call"]["name"]
        arguments = json.loads(message["function_call"]["arguments"])
        if function_name == "update_user_name":
                user_name = arguments["user_name"]
                argsment = {
                    'update_date': now,
                    'user_name': user_name
                }
                lambda_dao.update_user_info(user_id, argsment)
                messages.append(
                    {
                        "role": "function",
                        "name": function_name,
                        "content": user_name,
                    }
                )
                second_response = call_secound_gpt(messages)
                answer = second_response["choices"][0]["message"]["content"]
        elif function_name == "update_hate_food":
                hate_food = arguments["hate_food"]
                argsment = {
                    'update_date': now,
                    'hate_food': hate_food
                }
                lambda_dao.update_user_info(user_id, argsment)
                messages.append(
                    {
                        "role": "function",
                        "name": function_name,
                        "content": hate_food,
                    }
                )
                second_response = call_secound_gpt(messages)
                answer = second_response["choices"][0]["message"]["content"]
                logger.info(second_response)
        elif function_name == "update_recipi":
                recipi = arguments["recipi"]
                argsment = {
                    'user_id': user_id,
                    'date': now,
                    'recipi': recipi
                }
                lambda_dao.put_recipi_info(argsment)
                messages.append(
                    {
                        "role": "function",
                        "name": function_name,
                        "content": recipi,
                    }
                )
                second_response = call_secound_gpt(messages)
                answer = second_response["choices"][0]["message"]["content"]
        elif function_name == "get_past_recipi":
                start_date = arguments["start_date"]
                end_date = arguments["end_date"]
                recipi_data = lambda_dao.get_recipi_data(user_id, start_date, end_date)
                recipi_data_pairs = [(item['date'], item['recipi']) for item in recipi_data['Items']]
                recipi_data_strings = [str(pair) for pair in recipi_data_pairs]
                message_string = "\n".join(map(str, recipi_data_strings))
                messages.append(
                    {
                        "role": "function",
                        "name": function_name,
                        "content": message_string,
                    }
                )
                second_response = call_secound_gpt(messages)
                answer = second_response["choices"][0]["message"]["content"]
                
    # 登録するアイテム情報
    talk_item = {
        'user_id': user_id,
        'date': now,
        'message': query , 
        'reply': answer
    } 

    lambda_dao.put_talk_history(talk_item)
    # 応答トークンを使って回答を応答メッセージで送る
    line_bot_api.reply_message(
        event.reply_token, TextSendMessage(text=answer))

# gptを呼び出す
def call_gpt(messages, functions):
    return openai.ChatCompletion.create(
        model= 'gpt-3.5-turbo-0613',
        temperature= 0.4,
        messages= messages,
        functions= functions,
        function_call="auto"
    )
    
# gpt2回目の呼び出し
def call_secound_gpt(messages):
    return openai.ChatCompletion.create(
        model= 'gpt-3.5-turbo-0613',
        temperature= 0.4,
        messages= messages
    )

# LINE Messaging APIからのWebhookを処理する
def lambda_handler(event, context):

    # リクエストヘッダーにx-line-signatureがあることを確認
    if 'x-line-signature' in event['headers']:
        signature = event['headers']['x-line-signature']

    body = event['body']
    # 受け取ったWebhookのJSONを目視確認できるようにINFOでログに吐く
    logger.info(body)

    try:
        webhook_handler.handle(body, signature)
    except InvalidSignatureError:
        # 署名を検証した結果、飛んできたのがLINEプラットフォームからのWebhookでなければ400を返す
        return {
            'statusCode': 400,
            'body': json.dumps('Only webhooks from the LINE Platform will be accepted.')
        }
    except LineBotApiError as e:
        # 応答メッセージを送ろうとしたがLINEプラットフォームからエラーが返ってきたらエラーを吐く
        logger.error('Got exception from LINE Messaging API: %s\n' % e.message)
        for m in e.error.details:
            logger.error('  %s: %s' % (m.property, m.message))

    return {
        'statusCode': 200,
        'body': json.dumps('Hello from Lambda!')
    }