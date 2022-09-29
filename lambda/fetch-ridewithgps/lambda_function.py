# This Lambda is for fetching user and ride info from the RideWithGPS API.

from common.cibic_common import *

# Python 3.8 lambda environment does not have requests https://stackoverflow.com/questions/58952947/import-requests-on-aws-lambda-for-python-3-8
# for a fix using Lambda Layers, see https://dev.to/razcodes/how-to-create-a-lambda-layer-in-aws-106m
import requests

clubId = os.environ['ENV_VAR_RWGPS_CLUB_ID']
apiKey = os.environ['ENV_VAR_RWGPS_API_KEY']
authToken = os.environ['ENV_VAR_RWGPS_AUTH_TOKEN']

def lambda_handler(event, context):
    requestReply = {}
    err = ''

    try:
        users = fetchUsers()
        for user in users:
            if not user.get('active') == True:
                continue
            if user.get('approved_at') == None:
                continue
            if not 'user' in user:
                continue

            userId = user['user']['id']
            displayName = str(user['user'].get('display_name'))
            rides = fetchUserRides(userId)
            print("User " + str(userId) + ": " + displayName + ", " +
                  str(len(rides)) + " rides")
        requestReply = processedReply()
    except:
        err = reportError()
        print('caught exception:', sys.exc_info()[0])
        requestReply = lambdaReply(420, str(err))

    return requestReply

def fetchUsers():
    """
    Fetch all the users from the RideWithGPS API. Return the JSON list. Throw
    an exception for error.
    """
    response = requests.get(
      'https://ridewithgps.com/clubs/' + str(clubId) + '/table_members.json?apikey=' +
      apiKey + '&version=2&auth_token=' + authToken)
    if response.status_code/100 == 2:
        return response.json()
    else:
        raise('RideWithGPS API request for members failed with code {}'.format(response.status_code))

def fetchUserRides(userId):
    """
    Fetch all the meta info for all the rides of userId from the RideWithGPS API.
    Return the JSON list. Throw an exception for error.
    """
    response = requests.get(
      'https://ridewithgps.com/users/' + str(userId) + '/trips.json?apikey=' +
      apiKey + '&version=2&auth_token=' + authToken)
    if response.status_code/100 == 2:
        return response.json()['results']
    else:
        raise('RideWithGPS API request for trips failed with code {}'.format(response.status_code))
