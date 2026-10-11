import cv2
import numpy as np

def preprocess(id, img):
    gray = cv2.cvtColor(img, cv2.COLOR_BGR2GRAY)
    blur = cv2.GaussianBlur(gray, (5, 5), 0)

    if id == 1:
        thresh = cv2.adaptiveThreshold(
            blur, 255,
            cv2.ADAPTIVE_THRESH_GAUSSIAN_C,
            cv2.THRESH_BINARY_INV,
            51, 11
        )
    else:
        _, thresh = cv2.threshold(blur, 0, 255, cv2.THRESH_BINARY_INV + cv2.THRESH_OTSU)

    return thresh

def get_omr_roi(thresh):
    contours, _ = cv2.findContours(thresh, cv2.RETR_EXTERNAL, cv2.CHAIN_APPROX_SIMPLE)
    if not contours:
        return None
    
    contours = sorted(contours, key=cv2.contourArea, reverse=True)
    
    for c in contours:
        area = cv2.contourArea(c)
        peri = cv2.arcLength(c, True)
        approx = cv2.approxPolyDP(c, 0.02 * peri, True)
        
        # The main container should be at least 20% of the image area
        if len(approx) == 4 and area > (thresh.shape[0] * thresh.shape[1] * 0.2):
            return approx
    return None

def detect_bubbles(thresh):
    kernel = np.ones((3,3), np.uint8)
    closing = cv2.morphologyEx(thresh, cv2.MORPH_CLOSE, kernel, iterations=3)

    contours, _ = cv2.findContours(closing, cv2.RETR_EXTERNAL, cv2.CHAIN_APPROX_SIMPLE)
    
    bubbles = []
    roi_area = thresh.shape[0] * thresh.shape[1]
    
    for c in contours:
        area = cv2.contourArea(c)
        perimeter = cv2.arcLength(c, True)
        
        if perimeter == 0: continue
        
        circularity = 4 * np.pi * area / (perimeter * perimeter + 1e-6)
        
        if (roi_area * 0.0001) < area < (roi_area * 0.01):
            _, _, w, h = cv2.boundingRect(c)
            aspect_ratio = w / float(h)
            
            if 0.8 < aspect_ratio < 1.2 and circularity > 0.84:
                extent = area / (w * h)
                
                if 0.6 < extent < 0.9: 
                    bubbles.append(c)   

    print(f"Bubbles successfully filtered: {len(bubbles)}")
    return bubbles

def sort_bubbles(bubbles):
    # 1. Sort all bubbles by X coordinate (separates the 4 vertical columns)
    bubbles = sorted(bubbles, key=lambda c: cv2.boundingRect(c)[0])
    
    final_sorted = []
    # 2. Divide into 4 vertical blocks (20 bubbles per column)
    for i in range(0, len(bubbles), 20):
        block = bubbles[i:i+20]
        # 3. Sort each column from top to bottom (Y coordinate)
        block = sorted(block, key=lambda c: cv2.boundingRect(c)[1])
        final_sorted.extend(block)
        
    return final_sorted

def get_answers(sorted_bubbles, fill_thresh, block_of_questions, questions_per_block, options_per_question):
    final_results = {}
    total_questions = questions_per_block * block_of_questions
    for q_idx in range(total_questions): # 0 to 19
        max_fill = 0
        selected_choice = -1
        
        # Base index for this question (Q1 starts at 0, Q2 starts at 4, etc.)
        question_start_idx = q_idx * options_per_question

        for col in range(options_per_question): # 0 to 3
            # Simple linear indexing for row-wise bubbles
            idx = question_start_idx + col
            contour = sorted_bubbles[idx]

            # Masking and pixel counting
            mask = np.zeros(fill_thresh.shape, dtype="uint8")
            cv2.drawContours(mask, [contour], -1, 255, -1)
            
            pixel_count = cv2.countNonZero(cv2.bitwise_and(fill_thresh, fill_thresh, mask=mask))

            # Threshold check (40% of the area filled)
            if pixel_count > max_fill and pixel_count > (cv2.contourArea(contour) * 0.4):
                max_fill = pixel_count
                selected_choice = col

        choices = [chr(x+65) for x in range(options_per_question)]
        answer_letter = choices[selected_choice] if selected_choice != -1 else "None"
        final_results[q_idx + 1] = answer_letter

    return final_results

def draw_choice_circle(image, q_num, choice_letter, color, sorted_bubbles, options_per_question=4):
    if choice_letter == "None":
        return
    
    # 1. Map 'A', 'B', 'C' to 0, 1, 2
    choices = [chr(x+65) for x in range(options_per_question)]
    col_idx = choices.index(choice_letter)
    
    # 2. Simple Linear Indexing:
    # (q_num - 1) gets the question index (0-19)
    # Multiply by 4 (options) to get the start of that question's row
    # Add col_idx to get the specific bubble
    bubble_idx = ((q_num - 1) * options_per_question) + col_idx
    
    # Safety check to ensure we don't crash if detection missed a bubble
    if bubble_idx >= len(sorted_bubbles):
        return

    # 3. Draw logic
    cnt = sorted_bubbles[bubble_idx]
    M = cv2.moments(cnt)
    if M["m00"] != 0:
        cX = int(M["m10"] / M["m00"])
        cY = int(M["m01"] / M["m00"])
        
        # Draw the circle on the image
        cv2.circle(image, (cX, cY), 15, color, 3)

def grade_and_visualize(image, sorted_bubbles, options_per_question, detected_answers, answer_key):
    total_score = 0
    
    for q_num, user_answer in detected_answers.items():
        correct_answer = answer_key.get(q_num)
        
        if user_answer == correct_answer:
            total_score += 2
            # Correct: Highlight the answer in Green
            draw_choice_circle(image, q_num, correct_answer, (0, 255, 0), sorted_bubbles, options_per_question)
            
        elif user_answer == "None":
            # Skipped: Highlight the correct answer in Orange/Yellow
            draw_choice_circle(image, q_num, correct_answer, (0, 165, 255), sorted_bubbles, options_per_question)
            
        else:
            total_score -= 1
            # Incorrect: Highlight user error in Red and correct answer in Green
            draw_choice_circle(image, q_num, user_answer, (0, 0, 255), sorted_bubbles, options_per_question)
            draw_choice_circle(image, q_num, correct_answer, (0, 255, 0), sorted_bubbles, options_per_question)

    # UI Overlay for results
    cv2.rectangle(image, (10, 10), (350, 80), (255, 255, 255), -1) # Background
    cv2.rectangle(image, (10, 10), (350, 80), (0, 0, 255), 2) # Border
    cv2.putText(image, f"Score: {total_score}", (20, 50), cv2.FONT_HERSHEY_SIMPLEX, 1.2, (255, 0, 0), 3)
    
    return image, total_score

def read_omr(ref, filled_image, block_of_questions, questions_per_block, options_per_question, key):
    ref_thresh_full = preprocess(1, ref)
    roi_points = get_omr_roi(ref_thresh_full)
    
    if roi_points is not None:
        x, y, w, h = cv2.boundingRect(roi_points)
        
        margin = 10 # To go inside the rectangle

        ref_roi = ref_thresh_full[y+margin:y+h-margin, x+margin:x+w-margin]

        fill_thresh_full = preprocess(2, filled_image)
        fill_roi = fill_thresh_full[y+margin:y+h-margin, x+margin:x+w-margin]
        filled_image_roi = filled_image[y+margin:y+h-margin, x+margin:x+w-margin].copy()

        circles = detect_bubbles(ref_roi)
        print(f"Detected {len(circles)} bubbles. Expected {block_of_questions * questions_per_block * options_per_question}")

        if len(circles) != (block_of_questions * questions_per_block * options_per_question):
            return filled_image, 0

        bubbles = sort_bubbles(circles)

        answers = get_answers(bubbles, fill_roi, block_of_questions, questions_per_block, options_per_question)
        
        result_image, final_score = grade_and_visualize(filled_image_roi, bubbles, options_per_question, answers, key)
        return result_image, final_score

    print("Error: Main OMR rectangle not found.")
    return filled_image, 0

# Config (Right now, for 20 questions only)
block_of_questions = 4
questions_per_block = 5
options_per_question = 4
key = {i+1: val for i, val in enumerate(["A", "B", "C", "D", "A", "B", "B", "C", "A", "D", "C", "B", "C", "C", "B", "A", "A", "C", "A", "C"])}

ref_img = cv2.imread("images/OMR_ref2.png")
fill_img = cv2.imread("images/OMR_filled2.png")

res_img, final_score = read_omr(ref_img, fill_img, block_of_questions, questions_per_block, options_per_question, key)
cv2.imshow("Graded OMR ROI", res_img)
cv2.waitKey(0)
cv2.destroyAllWindows()
print(f"Final Score: {final_score}")