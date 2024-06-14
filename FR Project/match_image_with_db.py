import cv2
import face_recognition
# import os
# import threading
from datetime import datetime, timedelta
import dlib
from scipy.spatial import distance
import numpy as np
from imutils import face_utils
from collections import Counter
import mysql.connector
from mysql.connector import Error


# multi person detection
EAR_THRESHOLD = 0.3
HEAD_MOVEMENT_THRESHOLD = 5  # Adjusted for sensitivity
LIP_MOVEMENT_THRESHOLD = 2  # Adjusted for sensitivity
MOVEMENT_BUFFER_DURATION = 5  # Duration in seconds for consistent movements
MOVEMENT_BUFFER_SIZE = 30  # Buffer size to track movements (30 frames for a 5-second window at 6 FPS)

detector = dlib.get_frontal_face_detector()
predictor_path = "shape_predictor_68_face_landmarks.dat"
predictor = dlib.shape_predictor(predictor_path)

(lStart, lEnd) = (42, 48)
(rStart, rEnd) = (36, 42)

known_face_encodings = []
known_face_names = []

movement_buffer = {
    "blinks": [],
    "head_movements": [],
    "lip_movements": []
}

output_labels = []  # Array to store the output labels


def create_connection():
    try:
        connection = mysql.connector.connect(
            host="162.241.120.118",
            user="cognisun_all",
            password="Cognisun@456",
            database="NetworkSSOUAT"
        )
        if connection.is_connected():
            print("Connected to MySQL database")
        return connection
    except Error as e:
        print(f"Error: {e}")
        return None


def load_images_for_person(emp_id):
    connection = create_connection()
    if connection is not None:
        cursor = connection.cursor()
        try:
            query = "SELECT photo1, photo2, photo3, photo4, photo5, photo6, photo7, photo8, photo9, photo10 FROM profile_pics WHERE user_id = %s"
            cursor.execute(query, (emp_id,))
            photos = cursor.fetchone()

            encodings = []
            for photo_blob in photos:
                if photo_blob is not None:
                    nparr = np.frombuffer(photo_blob, np.uint8)
                    image = cv2.imdecode(nparr, cv2.IMREAD_COLOR)
                    encodings.extend(face_recognition.face_encodings(image))
            return encodings
        except Error as e:
            print(f"Error retrieving employee photos: {e}")
        finally:
            cursor.close()
            connection.close()
    else:
        print("Database connection failed")
        return {"error": "Database connection failed"}


def update_known_faces(emp_id):
    encodings = load_images_for_person(emp_id)
    if encodings:
        known_face_encodings.extend(encodings)
        known_face_names.extend([emp_id] * len(encodings))


def reset_known_faces():
    global known_face_encodings, known_face_names
    known_face_encodings = []
    known_face_names = []


def eye_aspect_ratio(eye):
    A = distance.euclidean(eye[1], eye[5])
    B = distance.euclidean(eye[2], eye[4])
    C = distance.euclidean(eye[0], eye[3])
    ear = (A + B) / (2.0 * C)
    return ear


def update_movement_buffer(blinks, head_movements, lip_movements):
    global movement_buffer
    if len(movement_buffer["blinks"]) >= MOVEMENT_BUFFER_SIZE:
        movement_buffer["blinks"].pop(0)
    if len(movement_buffer["head_movements"]) >= MOVEMENT_BUFFER_SIZE:
        movement_buffer["head_movements"].pop(0)
    if len(movement_buffer["lip_movements"]) >= MOVEMENT_BUFFER_SIZE:
        movement_buffer["lip_movements"].pop(0)

    movement_buffer["blinks"].append(blinks)
    movement_buffer["head_movements"].append(head_movements)
    movement_buffer["lip_movements"].append(lip_movements)


def check_consistent_movement():
    if (sum(movement_buffer["blinks"]) >= 1 and
            sum(movement_buffer["head_movements"]) >= 1 and
            sum(movement_buffer["lip_movements"]) >= 1):
        return True
    return False


def is_live_movement(shape):
    leftEye = shape[lStart:lEnd]
    rightEye = shape[rStart:rEnd]
    leftEAR = eye_aspect_ratio(leftEye)
    rightEAR = eye_aspect_ratio(rightEye)
    ear = (leftEAR + rightEAR) / 2.0

    blinks = 1 if ear < EAR_THRESHOLD else 0

    (x, y, w, h) = cv2.boundingRect(np.array([shape[lStart:lEnd]]))
    head_movement = h / 2
    head_movements = 1 if head_movement > HEAD_MOVEMENT_THRESHOLD else 0

    top_lip = shape[50:53]
    bottom_lip = shape[56:59]
    top_mean = np.mean(top_lip, axis=0)
    bottom_mean = np.mean(bottom_lip, axis=0)
    lip_distance = abs(top_mean[1] - bottom_mean[1])
    lip_movements = 1 if lip_distance > LIP_MOVEMENT_THRESHOLD else 0

    update_movement_buffer(blinks, head_movements, lip_movements)

    return check_consistent_movement()


def compare_faces_and_check_liveness(frame, tolerance=0.5):
    face_locations = face_recognition.face_locations(frame)
    if not face_locations:
        output_labels.append("UNKNOWN")
        return ["UNKNOWN"]

    current_face_encodings = face_recognition.face_encodings(frame, face_locations)
    labels = []
    # print(known_face_encodings)

    for current_face_encoding, face_location in zip(current_face_encodings, face_locations):
        # print(current_face_encoding)
        matches = face_recognition.compare_faces(known_face_encodings, current_face_encoding, tolerance=tolerance)
        face_distances = face_recognition.face_distance(known_face_encodings, current_face_encoding)

        best_match_index = None
        if matches:
            best_match_index = min(range(len(face_distances)), key=lambda i: face_distances[i])

        label = "UNKNOWN"
        if best_match_index is not None and matches[best_match_index]:
            name = known_face_names[best_match_index]
            gray = cv2.cvtColor(frame, cv2.COLOR_BGR2GRAY)
            (top, right, bottom, left) = face_location
            rect = dlib.rectangle(left, top, right, bottom)

            shape = predictor(gray, rect)
            shape = face_utils.shape_to_np(shape)
            if is_live_movement(shape):
                label = f"{name} LIVE"
            else:
                label = name
        else:  # If face doesn't match any known faces, check for live movements
            gray = cv2.cvtColor(frame, cv2.COLOR_BGR2GRAY)
            (top, right, bottom, left) = face_location
            rect = dlib.rectangle(left, top, right, bottom)

            shape = predictor(gray, rect)
            shape = face_utils.shape_to_np(shape)
            if is_live_movement(shape):
                label = "UNKNOWN LIVE"
            else:
                label = "UNKNOWN"

        labels.append(label)
        output_labels.append(label)

    # Check if there have been no movements for more than 10 seconds
    if len(output_labels) > 60:  # 60 frames per second for 10 seconds
        if all(label == "UNKNOWN" for label in output_labels[-60:]):
            labels = ["UNKNOWN"] * len(labels)
        elif all(label == "UNKNOWN LIVE" for label in output_labels[-60:]):
            labels = ["UNKNOWN LIVE"] * len(labels)

    return labels


def process_frame(camera = cv2.VideoCapture(0)):
    start_time = datetime.now()
    while True:
        success, frame = camera.read()
        if not success:
            break

        rgb_frame = cv2.cvtColor(frame, cv2.COLOR_BGR2RGB)
        labels = compare_faces_and_check_liveness(rgb_frame, tolerance=0.5)

        for (top, right, bottom, left), label in zip(face_recognition.face_locations(frame), labels):
            color = (0, 255, 0) if "LIVE" in label else (0, 0, 255)
            cv2.putText(frame, label, (left, top - 10), cv2.FONT_HERSHEY_SIMPLEX, 0.9, color, 2)
            cv2.rectangle(frame, (left, top), (right, bottom), color, 2)

        cv2.imshow('Video', frame)

        if cv2.waitKey(1) & 0xFF == ord('q'):
            break

        elapsed_time = datetime.now() - start_time
        if elapsed_time > timedelta(seconds=15):  # Changed from 30 seconds to 10 seconds
            break

    camera.release()
    cv2.destroyAllWindows()
    # Determine the label that repeats the highest number of times
    if output_labels:
        most_common_label = Counter(output_labels).most_common(1)[0][0]
        print("Output labels:", output_labels)
        print("Result: Highest repeat label is:", most_common_label)

        label_counts = Counter(output_labels)
        total_labels = len(output_labels)
        employee_id_live_percentage = (label_counts[
                                           "employee_id LIVE"] / total_labels) * 100 if "employee_id LIVE" in label_counts else 0
        unknown_percentage = (label_counts["UNKNOWN"] / total_labels) * 100 if "UNKNOWN" in label_counts else 0

        if employee_id_live_percentage >= 70:
            final_message = "SCANNED CORRECTLY"
        elif unknown_percentage >= 70:
            final_message = "ENTER VALID I/P"

        print("Final message:", most_common_label)
        # show_final_message(most_common_label)
        return most_common_label
    else:
        print("No labels detected.")
        return None


# def show_final_message(message, camera = cv2.VideoCapture(0)):
#     success, frame = camera.read()
#     if success:
#         cv2.putText(frame, message, (50, 50), cv2.FONT_HERSHEY_SIMPLEX, 1, (0, 0, 255), 2, cv2.LINE_AA)
#         cv2.imshow('Video', frame)
#         cv2.waitKey(1000)  # Display the final message for 3 seconds
#         camera.release()
#         cv2.destroyAllWindows()


# if __name__ == "__main__":
#     emp_id = input("Enter Employee ID: ")
#     reset_known_faces()
#     update_known_faces(emp_id)
#
#     camera = cv2.VideoCapture(0)
#     output_labels = []  # Array to store the output labels
#
#     movement_buffer = {
#         "blinks": [],
#         "head_movements": [],
#         "lip_movements": []
#     }
#
#     frame_thread = threading.Thread(target=process_frame)
#     frame_thread.start()
#     frame_thread.join()

