# This Lambda for the API to query to take a timestamp, query the ride Postgres
# table, and return the rider location at the timestamp.

from common.cibic_common import *
import os
from datetime import datetime
import psycopg2

pgServer = os.environ['ENV_VAR_POSTGRES_SERVER']
pgDbName = os.environ['ENV_VAR_POSTGRES_DB']
pgUsername = os.environ['ENV_VAR_POSTGRES_USER']
pgPassword = os.environ['ENV_VAR_POSTGRES_PASSWORD']

def lambda_handler(event, context):
    requestReply = {}
    err = ''

    try:
        print('query-user-enrollments event data: ' + str(event))
        timestamp = datetime.fromisoformat('2022-07-02T11:32:00-07:00')

        conn = psycopg2.connect(host=pgServer, database=pgDbName,
                                user=pgUsername, password=pgPassword)
        cur = conn.cursor()

        # Get rides where the timestamp is between the start and end times,
        # find the higest idx of the waypoint whose timestamp is less than the timestamp,
        # call its coordinate prev_coordinate, then get the coordinate of the
        # following idx call it next_coordinate.
        sql = """
SELECT "rideId", "startTime", "endTime", "userId", role, flow,
       prev_timestamp,
       ST_X(prev_coordinate::geometry) AS prev_coordinate_x,
       ST_Y(prev_coordinate::geometry) AS prev_coordinate_y,
       next_timestamp,
       ST_X(next_coordinate::geometry) AS next_coordinate_x,
       ST_Y(next_coordinate::geometry) AS next_coordinate_y
FROM (SELECT ride."rideId", "startTime", "endTime", "userId", role, flow,
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
  WHERE "startTime" <= '{2}' AND '{2}' <= "endTime") as q
        """.format(CibicResources.Postgres.Rides, CibicResources.Postgres.WaypointsRaw,
                   timestamp.astimezone().strftime("%Y-%m-%d %H:%M:%S%z"))
        cur.execute(sql)

        for ride in cur.fetchall():
            prevTimestamp = ride[6]
            prevCoordinateX = ride[7]
            prevCoordinateY = ride[8]
            nextTimestamp = ride[9]
            nextCoordinateX = ride[10]
            nextCoordinateY = ride[11]
            if nextTimestamp == None:
                # This happens when timestamp is after the last main zone waypoint.
                continue
            if prevTimestamp > nextTimestamp:
                # This shouldn't happen but will confuse the interpolation so check.
                continue

            # Interpolate the coordinate at the timestamp.
            progress = (timestamp - prevTimestamp) / (nextTimestamp - prevTimestamp)
            x = prevCoordinateX + (nextCoordinateX - prevCoordinateX) * progress
            y = prevCoordinateY + (nextCoordinateY - prevCoordinateY) * progress

            rideId = ride[0]
            userId = ride[3]
            print("Debug userId " + userId + " rideId " + rideId + " (" + str(x) + ", " + str(y) + ")")

        conn.commit()
        cur.close()

        requestReply = lambdaReply(200, [])
    except:
        err = reportError()
        print('caught exception:', sys.exc_info()[0])
        return lambdaReply(420, str(err))

    return requestReply
