import json
import logging
import boto3
import datetime
from botocore.exceptions import ClientError
from boto3.dynamodb.conditions import Key, Attr

# dynamodb
dynamodb = boto3.resource('dynamodb')
dynamodb_client = boto3.client('dynamodb')
talk_history = dynamodb.Table('talk_history')
user_table = dynamodb.Table('user_info')
recipi_info = dynamodb.Table('recipi_info')

# INFOレベル以上のログメッセージを拾うように設定する
logger = logging.getLogger()
logger.setLevel(logging.INFO)

# ログ出力のフォーマットをカスタマイズ
formatter = logging.Formatter('%(asctime)s - %(name)s - %(levelname)s - %(message)s')
# ログハンドラを作成し、フォーマッタを設定
ch = logging.StreamHandler()
ch.setFormatter(formatter)
# ロガーにハンドラを追加
logger.addHandler(ch)

def handle_dynamodb_exception(func):
    def wrapper(*args, **kwargs):
        try:
            return func(*args, **kwargs)
        except ClientError as e:
            error_message = f"{func.__name__}でエラーが発生しました: {e}"
            logger.error(error_message, exc_info=True)
            # エラーを再度raiseして、呼び出し元にエラーを伝える
            raise 
    return wrapper

# limitの数値をインクリメント
@handle_dynamodb_exception
def increment_limit(user_id):
    response = user_table.update_item(
        Key={'user_id': user_id},
        UpdateExpression='ADD #limit :inc',
        ExpressionAttributeNames={'#limit': 'limit'},
        ExpressionAttributeValues={':inc': 1},
        ReturnValues="UPDATED_NEW")
    # 'Attributes'キーが存在し、その中に'limit'キーが存在することを確認
    if 'Attributes' in response and 'limit' in response['Attributes']:
        # 'limit'の値を返す
        return response['Attributes']['limit']
    else:
        # エラーメッセージをログに出力
        print(f"Error: Failed to update limit for user_id {user_id}")
        return None

# ユーザー情報を取得する、なければNone
@handle_dynamodb_exception
def get_user_info(user_id):
    response =  user_table.get_item(Key={'user_id': user_id})
     # 'Item'キーがない場合、Noneを返す
    return response.get('Item', None)

# 会話履歴を取得する
@handle_dynamodb_exception
def get_talk_history(user_id, limit):
    return talk_history.query(
        KeyConditionExpression=Key('user_id').eq(user_id),
        # 降順にソート
        ScanIndexForward=False, 
        # 最新x件を取得
        Limit=limit 
    )

# 採用レシピ履歴を取得する
@handle_dynamodb_exception
def get_recipi_data(user_id, start_date, end_date):
    return recipi_info.query(
        KeyConditionExpression=Key('user_id').eq(user_id) & Key('date').between(start_date, end_date),
        # 降順にソート
        ScanIndexForward=False, 
        Limit=20
    )
    
# 採用レシピを登録する
@handle_dynamodb_exception
def put_recipi_info(item):
    return recipi_info.put_item(Item=item)

# 新しいユーザーを登録する
@handle_dynamodb_exception
def put_user_info(item):
    return user_table.put_item(Item=item)

# 新しい会話履歴を登録する
@handle_dynamodb_exception
def put_talk_history(item):
    return talk_history.put_item(Item=item)

# ユーザー情報を更新する
@handle_dynamodb_exception
def update_user_info(user_id, argsment):
    update_expression, expression_attribute_values = get_update_params(argsment)
    return user_table.update_item(
        Key={"user_id": user_id},
        UpdateExpression=update_expression,
        ExpressionAttributeValues=expression_attribute_values,
        ReturnValues="UPDATED_NEW"
    )
    
def get_update_params(body):
    """Given a dictionary we generate an update expression and a dict of values to update a dynamodb table."""
    update_expression = "SET "
    expression_attribute_values = {}
    for key, value in body.items():
        if value: # check if the value is not empty
            update_expression += f"{key} = :{key}, "
            expression_attribute_values[f":{key}"] = value
    update_expression = update_expression[:-2] # remove the last comma and space
    return update_expression, expression_attribute_values