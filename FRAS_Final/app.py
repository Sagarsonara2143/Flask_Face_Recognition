import os
import time
from flask_cors import CORS
from datetime import datetime, timedelta
from flask import Flask, request, jsonify, render_template
import cv2
import numpy as np
import mysql.connector
import dlib
from match_image_with_db import *
import threading
import math
import psycopg2
import face_recognition
import pytz

app = Flask(__name__)
CORS(app)

def get_datetime():
    ist_timezone = pytz.timezone('Asia/Kolkata')
    ist_now = datetime.now(ist_timezone)
    curr_time = ist_now.strftime('%Y-%m-%d %H:%M:%S')
    return curr_time


def db_con():
    conn = mysql.connector.connect(
        host="162.241.120.118",
        user="cognisun_all",
        password="Cognisun@456",
        database="NetworkSSOUAT"
    )
    print("DataBase Connected")
    return conn


def haversine_distance(lat1, lon1, lat2, lon2):
    R = 6371
    lat1, lon1, lat2, lon2 = map(math.radians, [lat1, lon1, lat2, lon2])
    dlat = lat2 - lat1
    dlon = lon2 - lon1
    a = math.sin(dlat/2)**2 + math.cos(lat1) * math.cos(lat2) * math.sin(dlon/2)**2
    c = 2 * math.atan2(math.sqrt(a), math.sqrt(1-a))
    distance = R * c
    return distance * 1000  # Convert to meters




@app.route("/update_photo/<member_id>/<create_by>", methods=['POST'])
def update_photos(member_id, create_by):
    if 'image' not in request.files:
        print("No image part in the request")
        return jsonify({"message": "No image part in the request"}), 400

    image = request.files['image']
    print(image)

    if image.filename == '':
        return jsonify({"message": "No image selected for uploading"}), 400

    if image:
        img_binary = image.read()
        nparr = np.frombuffer(img_binary, np.uint8)
        img_cv = cv2.imdecode(nparr, cv2.IMREAD_COLOR)
        # Encode image for face recognition
        image_encodings = face_recognition.face_encodings(img_cv)
        if not image_encodings:
            print("No face detected in the Captured image.")
            return jsonify({"message": "No face detected in the Captured image."}), 400
    
        # Encode image back to binary format (JPEG)
        ret, img_encoded = cv2.imencode('.jpg', img_cv)
        if not ret:
            return jsonify({"message": "Image encoding failed"}), 500
        img_binary = img_encoded.tobytes()
    else:
        return jsonify({"message":"Image Not Fetched in API"})
    

    conn = db_con()
    cursor = conn.cursor()
    query = "CALL InsertProfilePics(%s, %s, %s, %s, %s)"
    params = [member_id,img_binary,img_binary, create_by, get_datetime()]
    cursor.execute(query, params)
    conn.commit()
    cursor.close()
    conn.close()
    return jsonify({"id": member_id, "message": "Photos Updated successfully"}), 201


def get_known_faces(user_id):
    conn = db_con()
    cursor = conn.cursor()
    cursor.execute(f"SELECT photo1 FROM profile_pics WHERE user_id = {user_id}")
    rows = cursor.fetchall()
    known_face_encodings = []
    known_face_names = []
    if rows:
        for row in rows:
            known_face_names.append(row[0])
            known_face_encodings.append(np.frombuffer(row[1], dtype=np.float64))
    else:
        return jsonify({"Message":"Image Not Registered in Databse. First Register and then Make Attendance"})
    conn.close()
    return known_face_encodings, known_face_names


@app.route("/check_attendance/<user_id>/<meeting_id>", methods=["POST"])
def check_attendance(user_id, meeting_id):
    print("Attendance Checking...")
    conn = db_con()
    cursor = conn.cursor()
    qu = f"SELECT attendancecode,timestamp from attendance where MemberID = '{user_id}' and MeetingID = '{meeting_id}'"
    cursor.execute(qu)
    result = cursor.fetchone()
    if result:
        if result[0] == "A":
            return jsonify({"message":"Attendance Not Registered"}),400
        else:
            return jsonify({"message":"Attendance already Registered","Timestamp":f"{result[1]}"}),200
    else:
        return jsonify({"message":"Meeting Not Available"}),500



@app.route("/take_attendance/<user_id>", methods=["POST"])
def take_attendance(user_id):
    try:
        meeting_id = request.form['MeetingId']
        lat = request.form['latitude']
        long = request.form['longitude']
    except Exception as e:
        print("Error in data get for Meeting Id or Lat or Long")
        return jsonify({"message": "Error fetching Meeting Id or Lat or Long."}), 400



    if lat is None or long is None:
        print("Lat or Long Not Recived from Front.")
        return jsonify({"message": "Error fetching location."}), 400

    if 'image' not in request.files:
        print("No image part in the attendance request")
        return jsonify({"message": "No image part in the attendance request."}), 400

    conn = db_con()
    cursor = conn.cursor()
    query = "SELECT meetingid,venueid,meetingdate,meetingstarttime,meetingendtime  FROM meeting WHERE meetingid = %s"
    
    cursor.execute(query, (meeting_id,))
    meeting = cursor.fetchone()
    if meeting:
        meeting_id = meeting[0]
        venue_id = meeting[1]
        meeting_date = meeting[2]
        start_time = meeting[3]
        end_time = meeting[4]
      
        # Ensure start_time is a datetime.time object
        if isinstance(end_time, timedelta):
            end_time = (datetime.min + end_time).time()

       
        # Ensure start_time is a datetime.time object
        if isinstance(start_time, timedelta):
            start_time = (datetime.min + start_time).time()

        # Combine the date and start time into a single datetime object      
        start_datetime = datetime.combine(meeting_date, start_time)
        end_datetime = datetime.combine(meeting_date, end_time)
        
        timestamp = get_datetime()
        timestamp = datetime.strptime(timestamp, '%Y-%m-%d %H:%M:%S')

        # TODO start time frace period - attandance can taken before 30 minutes to start meeting
        if end_datetime > timestamp >= start_datetime - timedelta(minutes=30):
            latitude = float(lat)
            longitude = float(long)
            print("Your Lat-long",latitude, longitude)
            # print("timestamp",timestamp)

            venue_q = f"SELECT latitude, longitude FROM address WHERE addressid = '{venue_id}'"
            # print(venue_q)
            cursor.execute(venue_q)
            venue = cursor.fetchone()
            if not venue:
                return jsonify({"message": "Venue not found"}), 404
            else:
                venue_lat = float(venue[0])
                venue_long = float(venue[1])
                print("Venue Lat-Long : ", venue_lat, venue_long)

            distance = haversine_distance(latitude, longitude, venue_lat, venue_long)
            print("Distance from venue:", distance)
            if distance > 50:
                return jsonify({"message": "Geolocation is not within the configured distance.", "Distance in Meter": distance, "Note": "Picture is taken out of permissible geolocation range (50m)."}), 401


            qu = f"SELECT MemberID, MeetingID, attendancecode from attendance where MemberID = '{user_id}' and MeetingID = '{meeting_id}'"
            cursor.execute(qu)
            result = cursor.fetchone()
            if result:
                if result[2] == "A":
                    print(request)
                    print("Taking attendance...")

                    if 'image' not in request.files:
                        return jsonify({"message": "No image part in the attendance request."}), 400

                    # Fetch user's stored profile picture
                    query = "SELECT photo1 FROM profile_pics WHERE user_id = %s"
                    cursor.execute(query, (user_id,))
                    results = cursor.fetchall()

                    if not results:
                        print(f"User Not Found")
                        return jsonify({"message": "Please do register with attendance coordinator."}), 404
                    
                    # Read and process live image
                    live_image = request.files['image']
                    print("Live Image : ", live_image)
                    live_image_binary = live_image.read()

                    live_image_np = np.frombuffer(live_image_binary, np.uint8)
                    live_image_cv = cv2.imdecode(live_image_np, cv2.IMREAD_COLOR)

                    # Encode live image for face recognition
                    live_image_encodings = face_recognition.face_encodings(live_image_cv)
                    if not live_image_encodings:
                        print("No face detected in the live image")
                        return jsonify({"message": "No face detected in the live image"}), 400

                    live_image_encoding = live_image_encodings[0]

                    # Perform face recognition with stored images
                    match_found = False
                    threshold = 0.3

                    for result in results:
                        stored_image_binary = result[0]
                        stored_image_np = np.frombuffer(stored_image_binary, np.uint8)
                        stored_image_cv = cv2.imdecode(stored_image_np, cv2.IMREAD_COLOR)

                        stored_image_encodings = face_recognition.face_encodings(stored_image_cv)
                        if not stored_image_encodings:
                            continue

                        stored_image_encoding = stored_image_encodings[0]

                        # Compare faces and calculate distance
                        matches = face_recognition.compare_faces([stored_image_encoding], live_image_encoding)
                        distance = face_recognition.face_distance([stored_image_encoding], live_image_encoding)[0]

                        print("Match Distance : ", distance)

                        if matches[0] and distance < threshold:
                            match_found = True
                            break

                    if match_found:
                        if timestamp > start_datetime + timedelta(minutes=30):
                            status = "L"
                        else:
                            status = "P"

                        try:
                            conn = db_con()
                            cursor = conn.cursor()
                            update_query = f"UPDATE attendance SET attendancecode='{status}', latitude='{latitude}', longitude='{longitude}', timestamp='{timestamp}', type='Face' WHERE MemberID = '{user_id}' AND MeetingID = '{meeting_id}'"
                            cursor.execute(update_query)
                            conn.commit()
                            cursor.close()
                            conn.close()
                            print("Attendance taken successfully")
                            return jsonify({"timestamp": str(timestamp), "message": "Attendance marked successfully."}), 200
                        except Exception as e:
                            return jsonify({"message": f"Error in attendance update: {str(e)}"}), 500
                    else:
                        print("Oops. Face does not match.")
                        return jsonify({"message": "Oops. Face does not match."}), 404

                else:
                    print("Attendance already taken")
                    return jsonify({"message": "Attendance already taken"}), 403

        elif timestamp > end_datetime:
            return jsonify({"message": "Meeting has ended"}), 403
        else:
            return jsonify({"message": "Meeting has not started yet"}), 402
    else:
        return jsonify({"message": "Meeting not found"}), 404



@app.route("/check_photos/<user_id>", methods=['GET','POST'])
def check_photos(user_id):
    conn = db_con()
    cursor = conn.cursor()
    
    query = "SELECT * FROM profile_pics WHERE user_id = %s"
    cursor.execute(query, (user_id,))
    photos = cursor.fetchall()
    if photos:
        return jsonify({"ID":f"{user_id}","message": "Photos found"}), 200
    else:
        return jsonify({"message": "No photos found"}), 404


@app.route('/')
def start_api():
    curr_time = get_datetime()
    return f"API Calling from Final PY file - Date Time : {curr_time}"


if __name__ == "__main__":
    #    app.run(debug=False)        #for debub
    #  app.run(debug=True)        # for Run
    app.run(host="0.0.0.0", port=80)