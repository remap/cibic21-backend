# This Lambda is invoked periodically to scan ModeratedJournalingRequests
# for all entries after a startTimestamp with type 'live', finds rides for the
# user during the journal entry's timestamp and uses WaypointsRaw to get the
# rider's location at the timestamp. Then we update the
# ModeratedJournalingRequests with the location coordinate, flow, etc.
# Finally, we update the defaultLastLocationScanTime with the current timestamp
# to be ready for the next call.

from common.cibic_common import *
from boto3.dynamodb.conditions import Key
import os
from datetime import datetime, timezone
from decimal import Decimal
import psycopg2

dynamoDbResource = boto3.resource('dynamodb')
pgServer = os.environ['ENV_VAR_POSTGRES_SERVER']
pgDbName = os.environ['ENV_VAR_POSTGRES_DB']
pgUsername = os.environ['ENV_VAR_POSTGRES_USER']
pgPassword = os.environ['ENV_VAR_POSTGRES_PASSWORD']

# The key in ModeratedJournalingRequests for the metadata.
metadataKey = '1970-01-01T00:00:00+00:00'
lastLocationScanTimeKey = 'lastLocationScanTime'

def lambda_handler(event, context):
    requestReply = {}
    err = ''

    try:
        journalsTable = dynamoDbResource.Table(CibicResources.DynamoDB.ModeratedJournalingRequests)

        # Set a default value.
        lastLocationScanTime = '2022-07-01'
        # Get the metadata item.
        response = journalsTable.get_item(Key = { 'timestamp': metadataKey })
        if not 'Item' in response:
            # Create the initial record.
            journalsTable.put_item(Item = {
              'timestamp': metadataKey,
              'requestId': 'metadata',
              'body': '{ "type": "metadata", "userId": "metadata" }',
              lastLocationScanTimeKey: lastLocationScanTime
            })
        if 'Item' in response:
            item = response['Item']
            if lastLocationScanTimeKey in item:
                lastLocationScanTime = item[lastLocationScanTimeKey]

        # Get entries since lastLocationScanTime.
        now = datetime.now().astimezone(tz=timezone.utc).isoformat()
        response = journalsTable.scan(FilterExpression=Key('timestamp').gt(lastLocationScanTime))

        conn = psycopg2.connect(host=pgServer, database=pgDbName,
                                user=pgUsername, password=pgPassword)
        for item in response['Items']:
            if not (item.get('processed') == True and item.get('type') == 'live'):
                continue

            timestamp = datetime.fromisoformat(item['timestamp'])

            userId = item.get('userId')
            role = item.get('role')
            if userId == None or role == None:
                continue
            print('Checking ' + item['timestamp'] + ' for ' + userId + '/' + role)

            # Get rides for the userId/role where the timestamp is between the
            # start and end times, find the higest idx of the waypoint whose timestamp
            # is less than the timestamp, call its coordinate "prev_coordinate",
            # then get the coordinate of the following idx call it "next_coordinate".
            sql = """
SELECT "rideId", "startTime", "endTime", "userId", role, flow, "flowIsToWork", "flowName", pod, "podName", "podMemberJson",
       prev_timestamp,
       ST_X(prev_coordinate::geometry) AS prev_coordinate_x,
       ST_Y(prev_coordinate::geometry) AS prev_coordinate_y,
       next_timestamp,
       ST_X(next_coordinate::geometry) AS next_coordinate_x,
       ST_Y(next_coordinate::geometry) AS next_coordinate_y
FROM (SELECT ride."rideId", "startTime", "endTime", "userId", role, flow, "flowIsToWork", "flowName", pod, "podName", "podMemberJson",
       -- Get the timestamp and coordinate at prev_idx.
       (SELECT timestamp FROM {1} AS wp_prev
        WHERE wp_prev."rideId" = ride."rideId" AND wp_prev.idx = wp.prev_idx
        LIMIT 1) AS prev_timestamp,
       (SELECT coordinate FROM {1} AS wp_prev
        WHERE wp_prev."rideId" = ride."rideId" AND wp_prev.idx = wp.prev_idx
        LIMIT 1) AS prev_coordinate,
       -- Get the timestamp and coordinate at the index after prev_idx which is still in zone main. This may be null if after the end of the ride.
       (SELECT timestamp FROM {1} AS wp_next
        WHERE wp_next."rideId" = ride."rideId" AND wp_next.zone = 'main' AND wp_next.idx = wp.prev_idx + 1
        LIMIT 1) AS next_timestamp,
       (SELECT coordinate FROM {1} AS wp_next
        WHERE wp_next."rideId" = ride."rideId" AND wp_next.zone = 'main' AND wp_next.idx = wp.prev_idx + 1
        LIMIT 1) AS next_coordinate
  FROM {0} AS ride
  INNER JOIN (SELECT "rideId", MAX(idx) AS prev_idx
            FROM {1}
            WHERE zone = 'main' AND timestamp <= '{2}'
            GROUP BY "rideId") AS wp
  ON ride."rideId" = wp."rideId"
  WHERE "startTime" <= '{2}' AND '{2}' <= "endTime" AND
        "userId" = '{3}' AND role = '{4}') as q
            """.format(CibicResources.Postgres.Rides, CibicResources.Postgres.WaypointsRaw,
                       timestamp.astimezone().strftime("%Y-%m-%d %H:%M:%S%z"),
                       userId, role)
            cur = conn.cursor()
            cur.execute(sql)

            # There should only be one waypoint for the user at the timestamp,
            # so use fetchone.
            row = cur.fetchone()
            if row == None:
              continue

            prevTimestamp = row[11]
            prevCoordinateX = row[12]
            prevCoordinateY = row[13]
            nextTimestamp = row[14]
            nextCoordinateX = row[15]
            nextCoordinateY = row[16]
            if nextTimestamp == None:
                # This happens when timestamp is after the last main zone waypoint.
                continue
            if prevTimestamp > nextTimestamp:
                # This shouldn't happen but will confuse the interpolation so check.
                continue

            # Interpolate the coordinate at the timestamp.
            progress = (timestamp - prevTimestamp) / (nextTimestamp - prevTimestamp)
            rideLong = Decimal(str(prevCoordinateX + (nextCoordinateX - prevCoordinateX) * progress))
            rideLat = Decimal(str(prevCoordinateY + (nextCoordinateY - prevCoordinateY) * progress))

            rideId = row[0]
            flow = row[5]
            flowIsToWork = row[6]
            flowName = row[7]
            pod = row[8]
            podName = row[9]
            podMemberJson = row[10]
            print("Found rideId " + rideId + " flow " + flow + " (" + str(rideLong) + ", " + str(rideLat) + ")")
            journalsTable.update_item(
              Key = { 'timestamp': item['timestamp'] },
              UpdateExpression = 'SET #rideId = :rideId, #flow = :flow, ' +
                '#flowIsToWork = :flowIsToWork, #flowName = :flowName, ' +
                '#pod = :pod, #podName = :podName, #podMemberJson = :podMemberJson, ' +
                '#rideLong = :rideLong, #rideLat = :rideLat',
              ExpressionAttributeValues = {
                ':rideId': rideId,
                ':flow': flow,
                ':flowIsToWork': flowIsToWork,
                ':flowName': flowName,
                ':pod': pod,
                ':podName': podName,
                ':podMemberJson': podMemberJson,
                ':rideLong': rideLong,
                ':rideLat': rideLat
              },
              ExpressionAttributeNames = {
                '#rideId': 'rideId',
                '#flow': 'flow',
                '#flowIsToWork': 'flowIsToWork',
                '#flowName': 'flowName',
                '#pod': 'pod',
                '#podName': 'podName',
                '#podMemberJson': 'podMemberJson',
                '#rideLong': 'rideLong',
                '#rideLat': 'rideLat'
              })

            conn.commit()
            cur.close()

        # Update the metadata where lastLocationScanTime is now.
        journalsTable.update_item(
          Key = { 'timestamp': metadataKey },
          UpdateExpression = 'SET #lastLocationScanTime = :lastLocationScanTime',
          ExpressionAttributeValues = { ':lastLocationScanTime': now },
          ExpressionAttributeNames = { '#lastLocationScanTime': lastLocationScanTimeKey }
        )

        requestReply = lambdaReply(200, [])
    except:
        err = reportError()
        print('caught exception:', sys.exc_info()[0])
        return lambdaReply(420, str(err))

    return requestReply
