import base64
import boto3
from boto3.dynamodb.conditions import Key
from common.cibic_common import *

dynamoDbResource = boto3.resource('dynamodb')
rekognition = boto3.client('rekognition')
# Comprehend is not available in us-west-1, so use another region.
comprehend = boto3.client('comprehend', region_name='us-west-2')

snsTopicArn = os.environ['ENV_VAR_SNS_TOPIC_JOURNALING_DATA_READY']

def lambda_handler(event, context):
    unfilteredJournalingTable = dynamoDbResource.Table(
      CibicResources.DynamoDB.UnfilteredJournalingData)
    filteredJournalingTable = dynamoDbResource.Table(
      CibicResources.DynamoDB.FilteredJournalingData)

    try:
        print ('event data ' + str(event))

        if 'Records' in event:
            for rec in event['Records']:
                if 'Sns' in rec and rec['Sns']['TopicArn'] == snsTopicArn:
                    # Get each combined userId/sortKey sent by the processing Lambda.
                    combinedKeys = json.loads(rec['Sns']['Message'])
                    for combinedKey in combinedKeys:
                        if 'userId' in combinedKey and 'sortKey' in combinedKey:
                            userId = combinedKey['userId']
                            sortKey = combinedKey['sortKey']
                            dynamodbResponse = unfilteredJournalingTable.query(
                              KeyConditionExpression=Key('userId').eq(userId)
                                                   & Key('sortKey').eq(sortKey)
                            )
                            # The combined key is supposed to be unique, so assume one item.
                            if (dynamodbResponse['Count'] == 1):
                                item = dynamodbResponse['Items'][0]
                                if 'request' in item and 'body' in item['request']:
                                    body = json.loads(item['request']['body'])
                                    print('Moderating journal body for userId {}, sortKey {}, body {}'
                                      .format(userId, sortKey, body))
                                    moderateJournalEntry(body)
                                    # Replace the body in the item.
                                    item['request']['body'] = json.dumps(body)

                                # Store the possibly moderated item in DynamoDB.
                                filteredJournalingTable.put_item(Item = item)
                            else:
                                print('WARNING: No expected 1 item in unfilteredJournalingTable for userId {}, sortKey {}'
                                  .format(userId, sortKey))
                        else:
                            print('WARNING: No userId/sortKey in message {}'.format(combinedKey))
        else:
            return malformedMessageReply()
    except:
        err = reportError()
        print('caught exception:', sys.exc_info()[0])
        return lambdaReply(420, str(err))

    return processedReply()

def moderateJournalEntry(body):
    """
    Modify the body of the entry in place by redacting moderated text and
    removing moderated images.

    :param body: The journal body which has been converted from JSON into a dict.
    """
    # TODO: What are the important journal entry fields?
    fieldName = 'Bio'
    if fieldName in body:
        text = body[fieldName]

        # Check if the language is English.
        languageCode = ""
        detectLanguageResponse = comprehend.detect_dominant_language(
          Text = text
        )
        if 'Languages' in detectLanguageResponse:
            languageCode = detectLanguageResponse['Languages'][0]['LanguageCode']

        if languageCode == "en":
            # Use Detect PII Entities, which is only available in English.
            comprehendResponse = comprehend.detect_pii_entities(
              LanguageCode = languageCode,
              Text = text
            )
            if 'Entities' in comprehendResponse:
                body[fieldName] = redact(text, comprehendResponse['Entities'])

    fieldName = 'image'
    if fieldName in body and body[fieldName] != None and body[fieldName] != "":
        imagePath = body[fieldName]

        # Check the image directly in S3.
        response = rekognition.detect_moderation_labels(
            Image = { 'S3Object': {
              'Bucket': CibicResources.S3Bucket.JournalingImages,
              'Name': imagePath
            }}
        )
        if 'ModerationLabels' in response and response['ModerationLabels'] != []:
            labels = response['ModerationLabels']
            print('Removing image "{}". ModerationLabels: {}'.format(imagePath, labels))
            body[fieldName] = None

def redact(text, entities):
    """
    Return a new string where the substring of each detected entity is replaced
    by a string of stars of equal length.

    :param str text: The text with substrings to redact.
    :param entities: An array of dict with 'BeginOffset' and 'EndOffset' (as
      returned by AWS Comprehend Detect Entities).
    :return: The redacted text.
    :rtype: str
    """
    if len(entities) == 0:
        # Don't need to redact anything.
        return text

    for entity in entities:
        beginOffset = entity['BeginOffset']
        endOffset = entity['EndOffset']
        if endOffset <= beginOffset or beginOffset > len(text) or endOffset > len(text):
            # We don't really expect this.
            continue
        text = text[:beginOffset] + "*" * (endOffset - beginOffset) + text[endOffset:]

    return text
