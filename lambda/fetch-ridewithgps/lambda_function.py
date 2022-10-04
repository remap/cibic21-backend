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
        # Fetch the routes for the club.
        routes = fetchRoutes()
        for id, route in routes.items():
            print("Route " + str(id) + ' "' + str(route.get('name')) + '"')

        users = fetchUsers()
        for userId, user in users.items():
            if not user.get('active') == True:
                continue
            if user.get('approved_at') == None:
                continue
            if not 'user' in user:
                continue

            displayName = str(user['user'].get('display_name'))
            trips = fetchUserTrips(userId)
            routeInfo = ""
            if len(trips) <= 5:
                for tripId, tripMetaInfo in trips.items():
                    trip = fetchTrip(tripId)
                    for extra in trip.get('extras', []):
                        # Only show the club's routes.
                        if extra.get('type') == 'route' and extra.get('id') in routes:
                            routeInfo += (', trip ' + str(tripMetaInfo['id']) +
                              ' route ' + str(extra.get('id')))
                            break

            print("User " + str(userId) + ": " + displayName + ", " +
                  str(len(trips)) + " trips" + routeInfo)
        requestReply = processedReply()
    except:
        err = reportError()
        print('caught exception:', sys.exc_info()[0])
        requestReply = lambdaReply(420, str(err))

    return requestReply

def fetchRoutes():
    """
    Fetch all the routes for clubId (defined by the environment variable) from
    the RideWithGPS API. Return a dict where the key is the route ID and the
    value is the route JSON. Throw an exception for error.
    """
    response = requests.get(
      'https://ridewithgps.com/clubs/' + str(clubId) + '/routes.json?version=3&apikey=' +
      apiKey + '&auth_token=' + authToken)
    if response.status_code/100 == 2:
        result = {}
        for route in response.json()['results']:
            result[route['id']] = route
        return result
    else:
        raise ValueError('RideWithGPS API request for routes failed with code {}'.format(response.status_code))

def fetchUsers():
    """
    Fetch all the users for clubId (defined by the environment variable) from
    the RideWithGPS API. Return a dict where the key is the user ID and the
    value is the user JSON. Throw an exception for error.
    """
    response = requests.get(
      'https://ridewithgps.com/clubs/' + str(clubId) + '/table_members.json?version=3&apikey=' +
      apiKey + '&auth_token=' + authToken)
    if response.status_code/100 == 2:
        result = {}
        for user in response.json():
            result[user['user_id']] = user
        return result
    else:
        raise ValueError('RideWithGPS API request for users failed with code {}'.format(response.status_code))

def fetchUserTrips(userId):
    """
    Fetch the meta info for all the trips of userId from the RideWithGPS API.
    Return a dict where the key is the trip ID and the value is the trip JSON.
    Throw an exception for error.
    """
    response = requests.get(
      'https://ridewithgps.com/users/' + str(userId) + '/trips.json?version=2&apikey=' +
      apiKey + '&auth_token=' + authToken)
    if response.status_code/100 == 2:
        result = {}
        for trip in response.json()['results']:
            result[trip['id']] = trip
        return result
    else:
        raise ValueError('RideWithGPS API request for trips failed with code {}'.format(response.status_code))

def fetchTrip(tripId):
    """
    Fetch the give trip from the RideWithGPS API. Return the JSON list.
    Throw an exception for error.
    """
    response = requests.get(
      'https://ridewithgps.com/trips/' + str(tripId) + '.json?version=3&apikey=' +
      apiKey + '&auth_token=' + authToken)
    if response.status_code/100 == 2:
        return response.json()
    else:
        raise ValueError('RideWithGPS API request for trip failed with code {}'.format(response.status_code))
