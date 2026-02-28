import os
import uuid
import traceback
import smtplib
from email.mime.text import MIMEText
from email.mime.multipart import MIMEMultipart
from flask import Flask, request, jsonify
from flask_cors import CORS
from ultralytics import YOLO
import cv2
from PIL import Image
import numpy as np

# Load BLIP models from vision_llm directly
from vision_llm import analyze_cleanliness

BASE_DIR = os.path.dirname(os.path.abspath(__file__))
app = Flask(__name__, static_folder=os.path.join(BASE_DIR, '../frontend'), static_url_path='/')
CORS(app)

# Load YOLO models
ppe_model = YOLO(os.path.join(BASE_DIR, "foodsafety.pt"))
kitchen_model = YOLO(os.path.join(BASE_DIR, "kitchenobj.pt"))

ADMIN_EMAIL = "charanrangu2306@gmail.com"

def send_admin_email(subject, body, recipient=None):
    """
    Send email alerts to admin.
    Uses Gmail SMTP. Requires a Gmail App Password for the sender account.
    """
    to_email = recipient or ADMIN_EMAIL
    print(f"EMAIL TRIGGERED to {to_email}: {subject}")

    SMTP_SERVER = "smtp.gmail.com"
    SMTP_PORT = 587
    SENDER_EMAIL = "charanrangu2306@gmail.com"
    SENDER_PASSWORD = os.environ.get("GMAIL_APP_PASSWORD", "")

    if not SENDER_PASSWORD:
        print("EMAIL SKIPPED: No SENDER_PASSWORD configured. Set a Gmail App Password in app.py.")
        print(f"--- EMAIL CONTENT ---\nTo: {to_email}\nSubject: {subject}\n{body}\n--- END ---")
        return False

    try:
        msg = MIMEMultipart()
        msg['From'] = SENDER_EMAIL
        msg['To'] = to_email
        msg['Subject'] = subject
        msg.attach(MIMEText(body, 'plain'))
        server = smtplib.SMTP(SMTP_SERVER, SMTP_PORT)
        server.starttls()
        server.login(SENDER_EMAIL, SENDER_PASSWORD)
        server.send_message(msg)
        server.quit()
        print(f"EMAIL SENT SUCCESSFULLY to {to_email}")
        return True
    except Exception as e:
        print(f"EMAIL FAILED: {str(e)}")
        return False

@app.route('/')
def index():
    return app.send_static_file('index.html')

@app.route('/analyze', methods=['POST'])
def analyze():
    if 'image' not in request.files:
        return jsonify({"error": "No image part"}), 400
    
    file = request.files['image']
    if file.filename == '':
        return jsonify({"error": "No selected image"}), 400
    
    try:
        # Save the original image with a unique name
        task_id = str(uuid.uuid4())
        image_path = os.path.join(BASE_DIR, f"temp_{task_id}.jpg")
        file.save(image_path)
        print(f"DEBUG [{task_id}]: Saved image to {image_path}, size: {os.path.getsize(image_path)}")
        
        if os.path.getsize(image_path) == 0:
            return jsonify({"error": "Empty image uploaded"}), 400
        
        # Analyze with vision_llm (BLIP)
        print(f"DEBUG [{task_id}]: Starting vision_llm analysis...")
        caption, hygiene_score = analyze_cleanliness(image_path)
        print(f"DEBUG [{task_id}]: vision_llm complete. Caption: {caption}")
        
        # Analyze with YOLO
        print(f"DEBUG [{task_id}]: Starting YOLO analysis...")
        img_pil = Image.open(image_path).convert("RGB")
        img_cv2 = cv2.cvtColor(np.array(img_pil), cv2.COLOR_RGB2BGR)
        h_img, w_img, _ = img_cv2.shape
        
        # Increased confidence to avoid noise
        ppe_results = ppe_model(img_cv2, conf=0.35)
        kitchen_results = kitchen_model(img_cv2, conf=0.40)
        print(f"DEBUG [{task_id}]: YOLO analysis complete.")
        
        detected_ppe = []
        violations = []
        detections = []
        
        person_detected = any(ppe_results[0].names[int(box.cls)].lower() == 'person' for box in ppe_results[0].boxes)
        gloves_detected = any(ppe_results[0].names[int(box.cls)].lower() == 'gloves' for box in ppe_results[0].boxes)
        cap_detected = any(ppe_results[0].names[int(box.cls)].lower() == 'medical_cap' for box in ppe_results[0].boxes)
    
        # Scoring logic with unique penalty tracking
        unique_violations = set()
        
        if person_detected:
            if not cap_detected: unique_violations.add("Missing Medical Cap")
            if not gloves_detected: unique_violations.add("Missing Gloves")
            
        for box in ppe_results[0].boxes:
            conf = float(box.conf)
            cls_id = int(box.cls)
            label = ppe_results[0].names[cls_id]
            
            x1, y1, x2, y2 = map(int, box.xyxy[0])
            x_norm, y_norm, w_norm, h_norm = x1/w_img, y1/h_img, (x2-x1)/w_img, (y2-y1)/h_img
            
            if label.lower() in ['no_gloves', 'without_mask', 'without_cap', 'no_apron'] and not person_detected:
                continue
                
            status = 'ok'
            if label.lower() in ['no_gloves', 'without_mask', 'without_cap', 'no_apron']:
                status = 'bad'
                v_msg = label.replace('_', ' ').replace('no ', 'missing ').replace('without ', 'missing ').title()
                unique_violations.add(v_msg)
            elif label.lower() in ['gloves', 'medical_cap', 'apron', 'with_mask', 'person']:
                detected_ppe.append(label.replace('_', ' '))
                if label.lower() == 'person': status = 'info'
                
            detections.append({
                'label': label.replace('_', ' '),
                'x': int(x_norm * 500), 'y': int(y_norm * 300), 'w': int(w_norm * 500), 'h': int(h_norm * 300),
                'status': status
            })
            
        for box in kitchen_results[0].boxes:
            conf = float(box.conf)
            cls_id = int(box.cls)
            label = kitchen_results[0].names[cls_id]
            
            # Fire and Smoke are always high priority, others need higher confidence
            if label.lower() not in ['fire', 'smoke'] and conf < 0.50:
                continue
            if label.lower() in ['fire', 'smoke'] and conf < 0.25:
                continue
                
            x1, y1, x2, y2 = map(int, box.xyxy[0])
            x_norm, y_norm, w_norm, h_norm = x1/w_img, y1/h_img, (x2-x1)/w_img, (y2-y1)/h_img
            
            status = 'ok'
            if label.lower() in ['fire', 'smoke', 'no_apron', 'without_mask', 'mask_weared_incorrect']:
                status = 'bad'
                v_msg = label.replace('_', ' ').title()
                unique_violations.add(v_msg)
            elif label.lower() in ['apron', 'with_mask']:
                detected_ppe.append(label.replace('_', ' '))
                
            detections.append({
                'label': label.replace('_', ' '),
                'x': int(x_norm * 500), 'y': int(y_norm * 300), 'w': int(w_norm * 500), 'h': int(h_norm * 300),
                'status': status
            })
            
        # Apply unique penalties
        for v in unique_violations:
            violations.append(f"Violation: {v}" if "Fire" not in v and "Smoke" not in v else f"Hazard: {v}")
            if "Fire" in v or "Smoke" in v: hygiene_score -= 25
            elif "Missing" in v: hygiene_score -= 15
            else: hygiene_score -= 10

        hygiene_score = max(5, min(100, int(hygiene_score))) # Never truly 0 unless catastrophic
        
        # Calculate Risk Level
        risk_level = "Low"
        risk_reason = "Facility meets all primary safety standards."
        
        if any("hazard" in v.lower() for v in violations):
            risk_level = "High"
            risk_reason = "Critical hazards (Fire/Smoke) detected in facility."
        elif hygiene_score < 60:
            risk_level = "High"
            risk_reason = f"Compliance score ({hygiene_score}%) is below minimum safety threshold (60%)."
        elif hygiene_score < 80:
            risk_level = "Medium"
            risk_reason = "Minor violations detected; improved monitoring required."
        else:
            risk_level = "Low"
            risk_reason = "Quality standards maintained; no immediate action required."

        # Deduplicate
        detected_ppe = list(set(detected_ppe))
        violations = list(set(violations))
        if os.path.exists(image_path):
            os.remove(image_path)
            
        if risk_level in ["High", "Medium"]:
            # Build detailed violation table for email
            violation_details = ""
            for v in violations:
                category = "Safety" if "Hazard" in v or "Fire" in v or "Smoke" in v else "PPE"
                severity = "HIGH" if "Hazard" in v or "Fire" in v or "Smoke" in v else "MEDIUM"
                item_name = v.replace('Violation: ', '').replace('Hazard: ', '')
                violation_details += f"  - [{severity}] {category}: {item_name}\n"
            
            ppe_details = ""
            for p in detected_ppe:
                ppe_details += f"  - [OK] {p}\n"

            subject = f"🚨 ALERT: {risk_level} Risk Hygiene Violation Detected"
            body = f"""════════════════════════════════════
   AI AUDIT ALERT — {risk_level.upper()} RISK
════════════════════════════════════

Task ID       : {task_id}
Audit Type    : Image Analysis
Timestamp     : {__import__('datetime').datetime.now().strftime('%Y-%m-%d %H:%M:%S')}

── COMPLIANCE SCORE ──
Score         : {hygiene_score}%
Risk Level    : {risk_level}
Risk Reason   : {risk_reason}

── VIOLATION BREAKDOWN ──
{violation_details if violation_details else '  No violations detected.'}

── PPE DETECTED (OK) ──
{ppe_details if ppe_details else '  No PPE items detected.'}

── AI SCENE DESCRIPTION ──
{caption}

════════════════════════════════════
This is an automated alert from the
HygieneCheck AI Audit System.
════════════════════════════════════
"""
            send_admin_email(subject, body)

        return jsonify({
            "compliance_score": hygiene_score,
            "risk_level": risk_level,
            "risk_reason": risk_reason,
            "detected_ppe": detected_ppe,
            "violations": violations,
            "detections": detections,
            "caption": caption
        })
    except Exception as e:
        print(f"CRITICAL ERROR in /analyze for task {task_id if 'task_id' in locals() else 'None'}:")
        traceback.print_exc()
        return jsonify({"error": str(e)}), 500

OUTPUT_FOLDER = os.path.join(BASE_DIR, "outputs")
os.makedirs(OUTPUT_FOLDER, exist_ok=True)

from flask import send_from_directory

@app.route('/outputs/<path:filename>')
def serve_output(filename):
    return send_from_directory(OUTPUT_FOLDER, filename)

@app.route('/feedback', methods=['POST'])
def submit_feedback():
    try:
        data = request.json
        subject = data.get('subject', 'No Subject')
        message = data.get('message', 'No Message Content')
        
        import datetime
        timestamp = datetime.datetime.now().strftime('%Y-%m-%d %H:%M:%S')
        
        email_body = f"""════════════════════════════════════
   USER FEEDBACK RECEIVED
════════════════════════════════════

Timestamp     : {timestamp}
Subject       : {subject}

── MESSAGE ──
{message}

════════════════════════════════════
This feedback was submitted via the
HygieneCheck AI Audit Dashboard.
════════════════════════════════════
"""
        send_admin_email(f"📝 Feedback: {subject}", email_body)
        
        return jsonify({"message": "Feedback submitted and sent to admin successfully"}), 200
    except Exception as e:
        return jsonify({"error": str(e)}), 500

@app.route('/analyze_video', methods=['POST'])
def analyze_video():
    task_id = str(uuid.uuid4())
    print(f"DEBUG [{task_id}]: Starting video analysis request")
    
    if 'video' not in request.files:
        return jsonify({"error": "No video part"}), 400
    
    file = request.files['video']
    if file.filename == '':
        return jsonify({"error": "No selected video"}), 400
    
    input_video_path = os.path.join(BASE_DIR, f"temp_{task_id}.mp4")
    file.save(input_video_path)
    
    try:
        cap = cv2.VideoCapture(input_video_path)
        if not cap.isOpened():
            return jsonify({"error": "Could not open video file"}), 500
            
        width = int(cap.get(cv2.CAP_PROP_FRAME_WIDTH))
        height = int(cap.get(cv2.CAP_PROP_FRAME_HEIGHT))
        fps = cap.get(cv2.CAP_PROP_FPS)
        if fps <= 0 or np.isnan(fps): fps = 24
        
        output_filename = f"processed_{task_id}.mp4"
        output_path = os.path.join(OUTPUT_FOLDER, output_filename)
        
        # Try H.264 first, fallback to MP4V
        fourcc = cv2.VideoWriter_fourcc(*'avc1')
        out = cv2.VideoWriter(output_path, fourcc, fps, (width, height))
        
        if not out.isOpened():
            print(f"DEBUG [{task_id}]: avc1 failed, trying mp4v")
            fourcc = cv2.VideoWriter_fourcc(*'mp4v')
            out = cv2.VideoWriter(output_path, fourcc, fps, (width, height))
            
        if not out.isOpened():
            return jsonify({"error": "Could not initialize video writer"}), 500
        
        frame_count = 0
        incidents = 0
        frequent_violations = []
        
        total_frames_in_video = int(cap.get(cv2.CAP_PROP_FRAME_COUNT))
        duration = total_frames_in_video / fps if fps > 0 else 0
        
        # Short videos (< 3s) need full analysis (no skipping) for accuracy
        skip_factor = 3 if duration >= 3 else 1
        print(f"DEBUG [{task_id}]: Processing video... (FPS: {fps}, Duration: {duration:.2f}s, SkipFactor: {skip_factor})")
        
        while True:
            ret, frame = cap.read()
            if not ret: break
            
            frame_count += 1
            # Speed optimization: Only run AI on selected frames
            if frame_count % skip_factor != 0:
                out.write(frame)
                continue

            ppe_results = ppe_model(frame, conf=0.30)
            kitchen_results = kitchen_model(frame, conf=0.35)
            
            frame_has_incident = False
            
            # Draw standard detections
            for box in ppe_results[0].boxes:
                label = ppe_results[0].names[int(box.cls)].lower()
                conf = float(box.conf)
                x1, y1, x2, y2 = map(int, box.xyxy[0])
                
                if label == 'person':
                    # Only draw person if no explicit violations are found below, or draw green if clean
                    # We'll handle this by drawing individuals first if bad
                    pass
                elif label in ['no_gloves', 'without_mask', 'without_cap', 'no_apron', 'mask_weared_incorrect']:
                    frame_has_incident = True
                    cv2.rectangle(frame, (x1, y1), (x2, y2), (0, 0, 255), 2)
                    v_msg = label.replace('_', ' ').replace('no ', 'Missing ').replace('without ', 'Missing ').title()
                    cv2.putText(frame, v_msg, (x1, y1-10), cv2.FONT_HERSHEY_SIMPLEX, 0.5, (0, 0, 255), 2)
                    if frame_count % (int(fps) * 2) == 0:
                        frequent_violations.append(v_msg)
                elif label in ['gloves', 'medical_cap', 'apron', 'with_mask']:
                    cv2.rectangle(frame, (x1, y1), (x2, y2), (0, 255, 0), 1)
                    cv2.putText(frame, label.title(), (x1, y1-5), cv2.FONT_HERSHEY_SIMPLEX, 0.4, (0, 255, 0), 1)

            for box in kitchen_results[0].boxes:
                label = kitchen_results[0].names[int(box.cls)].lower()
                conf = float(box.conf)
                x1, y1, x2, y2 = map(int, box.xyxy[0])
                
                if label in ['fire', 'smoke']:
                    frame_has_incident = True
                    cv2.rectangle(frame, (x1, y1), (x2, y2), (0, 0, 255), 3)
                    cv2.putText(frame, f"CRITICAL: {label.upper()}", (x1, y1-15), cv2.FONT_HERSHEY_SIMPLEX, 0.8, (0, 0, 255), 3)
                    if frame_count % (int(fps) * 3) == 0:
                        frequent_violations.append(f"HAZARD: {label.title()}")
                elif label in ['no_apron', 'without_mask', 'without_cap', 'no_gloves']:
                    frame_has_incident = True
                    cv2.rectangle(frame, (x1, y1), (x2, y2), (0, 0, 255), 2)
                    v_msg = label.replace('_', ' ').replace('no ', 'Missing ').replace('without ', 'Missing ').title()
                    cv2.putText(frame, v_msg, (x1, y1-10), cv2.FONT_HERSHEY_SIMPLEX, 0.5, (0, 0, 255), 2)
                    if frame_count % (int(fps) * 2) == 0:
                        frequent_violations.append(v_msg)
                    
            if frame_has_incident: incidents += 1
            out.write(frame)
            
        cap.release()
        out.release()
        
        frequent_violations = list(dict.fromkeys(frequent_violations))
        
        # Cleanup input
        if os.path.exists(input_video_path):
            os.remove(input_video_path)
            
        # Smarter scoring for video
        incident_ratio = incidents / frame_count if frame_count > 0 else 0
        compliance_score = 100 * (1 - incident_ratio)
        
        # Check for sustained hazards
        hazards_detected = any("HAZARD" in v for v in frequent_violations)
        risk_reason = "Continuous compliance maintained throughout footage."
        
        if hazards_detected:
            compliance_score *= 0.6 # 40% penalty for hazards
            risk_level = "High"
            risk_reason = "Recurring critical hazards (Fire/Smoke) detected during stream."
        elif compliance_score < 60:
            risk_level = "High"
            risk_reason = f"High ratio of safety incidents ({incidents} total) detected in footage."
        elif compliance_score < 85:
            risk_level = "Medium"
            risk_reason = "Periodic non-compliance incidents observed in video stream."
        else:
            risk_level = "Low"
            risk_reason = "Personnel and facility followed safety protocols consistently."
        
        score = max(5, int(compliance_score))
        print(f"DEBUG [{task_id}]: Video analysis complete. Score: {score}")
        
        if risk_level in ["High", "Medium"]:
            # Build detailed violation table for email
            violation_details = ""
            for v in frequent_violations:
                category = "Safety" if "HAZARD" in v else "PPE"
                severity = "HIGH" if "HAZARD" in v else "MEDIUM"
                item_name = v.replace('HAZARD: ', '')
                violation_details += f"  - [{severity}] {category}: {item_name}\n"

            subject = f"🎥 VIDEO ALERT: {risk_level} Risk Incident Recorded"
            body = f"""════════════════════════════════════
   VIDEO AUDIT ALERT — {risk_level.upper()} RISK
════════════════════════════════════

Task ID       : {task_id}
Audit Type    : Video Stream Analysis
Timestamp     : {__import__('datetime').datetime.now().strftime('%Y-%m-%d %H:%M:%S')}

── COMPLIANCE SCORE ──
Score         : {score}%
Risk Level    : {risk_level}
Risk Reason   : {risk_reason}

── VIDEO METRICS ──
Total Frames  : {frame_count}
Incident Frames: {incidents}
Incident Ratio: {(incidents/frame_count*100):.1f}% of frames

── VIOLATION BREAKDOWN ──
{violation_details if violation_details else '  No specific violations logged.'}

── CORRECTIVE ACTION REQUIRED ──
Please review the processed video at:
http://localhost:5000/outputs/{output_filename}

════════════════════════════════════
This is an automated alert from the
HygieneCheck AI Audit System.
════════════════════════════════════
"""
            send_admin_email(subject, body)

        return jsonify({
            "average_score": score,
            "total_frames": frame_count,
            "critical_incidents": incidents,
            "frequent_violations": frequent_violations,
            "risk_level": risk_level,
            "risk_reason": risk_reason,
            "processed_video_url": f"/outputs/{output_filename}"
        })
    except Exception as e:
        print(f"CRITICAL ERROR in /analyze_video for task {task_id}:")
        traceback.print_exc()
        if os.path.exists(input_video_path): os.remove(input_video_path)
        return jsonify({"error": str(e)}), 500

if __name__ == '__main__':
    app.run(host='0.0.0.0', port=5000, debug=True)
