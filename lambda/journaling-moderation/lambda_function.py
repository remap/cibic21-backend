import time
import boto3
from botocore.errorfactory import ClientError
from common.cibic_common import *

dynamoDbResource = boto3.resource('dynamodb')
s3 = boto3.client('s3')
rekognition = boto3.client('rekognition')
# Comprehend is not available in us-west-1, so use another region.
comprehend = boto3.client('comprehend', region_name='us-west-2')

imageUploadTimeoutSeconds = float(os.environ['ENV_LAMBDA_IMAGE_UPLOAD_TIMEOUT_SECONDS'])

def lambda_handler(event, context):
    moderatedRequestsTable = dynamoDbResource.Table(CibicResources.DynamoDB.ModeratedJournalingRequests)
    timestamp = ''
    requestId = ''
    journalType = ''
    userId = ''
    role = ''
    body = ''
    processed = False
    requestReply = {}
    err = ''

    try:
        print ('event data ' + str(event))
        stage = event['stage']

        if 'timestamp' in event and 'requestId' in event and 'body' in event:
            timestamp = event['timestamp']
            requestId = event['requestId']
            body = event['body']
            if 'type' in body:
                journalType = body['type']
            if 'userId' in body:
                userId = body['userId']
            if 'role' in body:
                role = body['role']

            print('Moderating journal body for requestId {}, userId {}, role {}, body {}'
              .format(requestId, userId, role, body))
            moderateJournalEntry(body)

            processed = True
            requestReply = processedReply()
        else:
            requestReply = malformedMessageReply()
    except:
        err = reportError()
        print('caught exception:', sys.exc_info()[0])
        requestReply = lambdaReply(420, str(err))

    if timestamp != '':
        # Store request data in moderated DynamoDB table.
        moderatedRequestsTable.put_item(Item = {
            'timestamp' : timestamp,
            'requestId': requestId,
            'type': journalType,
            'userId': userId,
            'role': role,
            'body' : json.dumps(body),
            'processed' : processed,
            'error' : str(err)
        })

    return requestReply

def moderateJournalEntry(body):
    """
    Modify the body of the entry in place by redacting moderated text and
    removing moderated images.

    :param body: The journal body which has been converted from JSON into a dict.
    """
    # TODO: What are the important journal entry fields?
    fieldName = 'answers'
    if fieldName in body:
        # Expect an array of values. Moderate any string.
        values = body[fieldName]
        for i in range(len(values)):
            text = values[i]
            if not type(text) is str:
                continue

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
                    values[i] = redact(text, comprehendResponse['Entities'])

    fieldName = 'images'
    imagesModerationLabels = []
    if fieldName in body and body[fieldName] != None and body[fieldName] != "":
        for imagePath in body[fieldName]:
            moderationLabels = None
            if not s3HasFile(CibicResources.S3Bucket.JournalingImages, imagePath,
                             imageUploadTimeoutSeconds):
                print('Error: After ' + str(imageUploadTimeoutSeconds) +
                  ' second timeout, cannot find S3 journal image: ' + imagePath)
                # Leave 'moderationLabels' as null, meaning "don't know".
            else:
                # Check the image directly in S3.
                response = rekognition.detect_moderation_labels(
                    Image = { 'S3Object': {
                      'Bucket': CibicResources.S3Bucket.JournalingImages,
                      'Name': imagePath
                    }}
                )
                if 'ModerationLabels' in response:
                    # This may be the empty list.
                    moderationLabels = response['ModerationLabels']
                    print('Image "{}". ModerationLabels: {}'.format(imagePath, moderationLabels))

            imagesModerationLabels.append({'image': imagePath, 'moderationLabels': moderationLabels})
    body['imagesModerationLabels'] = imagesModerationLabels

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

def s3HasFile(bucket, key, timeoutSeconds):
    """
    Repeatedly check if the S3 bucket has the object with the key, up until the timeout.

    :param bucket: The S3 bucket name.
    :param key: The S3 object key.
    :param timeoutSeconds: The timeout in seconds.
    :return: True if the S3 object exists, False if the object is not found after
      the timeout.
    :rtype: bool
    """
    startTime = time.perf_counter()
    while time.perf_counter() - startTime < timeoutSeconds:
        try:
            # Get the object's metadata (check if it exists).
            s3.head_object(Bucket=bucket, Key=key)
            return True
        except ClientError:
            # Object is not found (or other error). Keep trying.
            pass

        time.sleep(1)

    return False
