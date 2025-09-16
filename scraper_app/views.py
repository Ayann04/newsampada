import time
import re
import os
from openpyxl import Workbook, load_workbook
from django.shortcuts import render
from django.http import JsonResponse
from selenium.webdriver.support.ui import Select
from selenium import webdriver
from selenium.webdriver.chrome.service import Service
from selenium.webdriver.chrome.options import Options
from selenium.webdriver.common.by import By
from selenium.webdriver.support.ui import WebDriverWait
from selenium.webdriver.support import expected_conditions as EC
from webdriver_manager.chrome import ChromeDriverManager
from selenium.webdriver.common.keys import Keys
from PIL import Image
from io import BytesIO
from datetime import datetime
from .models import ScrapingStatus
from .models import ScrapedRecord
from .models import ScrapingRun
from django.http import HttpResponse
from openpyxl import Workbook
from .models import ScrapedRecord
from django.core.files.base import ContentFile


def get_status(request):
    # Find the latest run
    latest_run = ScrapingRun.objects.order_by("-started_at").first()

    # If we have one, fetch all its statuses
    if latest_run:
        statuses = latest_run.statuses.order_by("created_at")
    else:
        statuses = []

    return render(request, "scraper_app/status.html", {"statuses": statuses})

timestamp_2 = datetime.now().strftime("%Y%m%d_%H%M%S")
def parse_address(addr):
    parsed = {}
    patterns = {
        "Ward/Colony": r"Ward Colony\s*-\s*([^,\.]+)",
        "District": r"Distirct:?\s*([^,\.]+)",
        "Village": r"Village:?\s*([^,\.]+)",
        "Sub-Area/Road": r"Sub-Area\s*:?\s*([^,\.]+)",
        "Tehsil/Locality": r"Tehsil:?\s*([^,\.]+)",
        "PIN Code": r"pin-?(\d{6})",
        "Landmark": r"(\d+\s*m\s+from\s+[^p]+)",
    }

    for key, pattern in patterns.items():
        match = re.search(pattern, addr, re.IGNORECASE)
        if match:
            parsed[key] = match.group(1) or (match.group(2) if match.lastindex and match.lastindex >= 2 else '')
        else:
            parsed[key] = ""

    parsed["State"] = "Madhya Pradesh" if "Madhya Pradesh" in addr else ""
    parsed["Country"] = "India" if "India" in addr else ""
    return parsed




def save_to_db(all_sections):
    # Convert all_sections to dictionary
    data = {}
    for headings, data_texts in all_sections:
        for heading, value in zip(headings, data_texts):
            data[heading] = value

    ScrapedRecord.objects.create(
        registration_details = dict(zip(all_sections[0][0], all_sections[0][1])),
        seller_details = dict(zip(all_sections[1][0], all_sections[1][1])),
        buyer_details = dict(zip(all_sections[2][0], all_sections[2][1])),
        property_details = dict(zip(all_sections[3][0], all_sections[3][1])),
        khasra_details = dict(zip(all_sections[4][0], all_sections[4][1])),
    )




def trigger_scrape(request):
    new_run = ScrapingRun.objects.create()
    if request.method == 'POST':
        chrome_options = Options()
        chrome_options.add_argument("--start-maximized")
        service = Service() 
        driver = webdriver.Chrome(service=service, options=chrome_options)
        
        try:
            
            username = request.POST.get('username')  
            password = request.POST.get('password')
            district = request.POST.get('district')
            deed_type = request.POST.get('deed_type')
            date_too = request.POST.get("date_to")
            date_from = request.POST.get("date_from")
            date_from_fmt = datetime.strptime(date_from, "%Y-%m-%d").strftime("%d-%m-%Y")
            date_to_fmt = datetime.strptime(date_too, "%Y-%m-%d").strftime("%d-%m-%Y")
            ScrapingStatus.objects.create(run=new_run, message=f"Redirecting To ->  https://sampada.mpigr.gov.in/#/clogin {timestamp_2}")
            driver.get("https://sampada.mpigr.gov.in/#/clogin")
            time.sleep(5)
            english_to = driver.find_elements(By.CSS_SELECTOR,'div.ng-star-inserted>a')
            english_to[2].click()
            global GLOBAL_CAPTCHA_VALUE
            max_attempts = 10
            login_success = False
            ScrapingStatus.objects.create(run=new_run, message="Filling Username And Password To login")
            for attempt in range(max_attempts):
                try:    
                    driver.refresh()
                    time.sleep(10) 
                    username_input= driver.find_element(By.CSS_SELECTOR, "input#username")
                    username_input.send_keys(username)
                    time.sleep(2)
                    
                    password_input= driver.find_element(By.CSS_SELECTOR, "input#password")
                    password_input.send_keys(password)
                    
                    time.sleep(10)
                    #captcha resolving  1
                    elem = driver.find_element(By.CSS_SELECTOR, "div.input-group>img")
                    # Scroll into view to ensure visibility
                    driver.execute_script("arguments[0].scrollIntoView(true);", elem)
                    time.sleep(1)

                    # --- Get device pixel ratio ---
                    device_pixel_ratio = driver.execute_script("return window.devicePixelRatio")

                    # --- Take full-page screenshot ---
                    png = driver.get_screenshot_as_png()
                    image = Image.open(BytesIO(png))

                    # --- Get element coordinates and size ---
                    location = elem.location_once_scrolled_into_view
                    size = elem.size
                    ScrapingStatus.objects.create(run=new_run, message="Solving Captcha")
                    left = int(location['x'] * device_pixel_ratio)
                    top = int(location['y'] * device_pixel_ratio)
                    right = int((location['x'] + size['width']) * device_pixel_ratio)
                    bottom = int((location['y'] + size['height']) * device_pixel_ratio)

                    # --- Crop and save ---
                    cropped_image = image.crop((left, top, right, bottom))
                    cropped_image.save("captcha_element_precise.png")
                    buffer = BytesIO()
                    cropped_image.save(buffer, format="PNG")   # write the image into buffer
                    buffer.seek(0)  # rewind pointer

                    # Create status and attach the file
                    status = ScrapingStatus.objects.create(
                        run=new_run,
                        message="captcha_element_precise.png"
                    )
                    status.captcha_image.save(
                        f"captcha_{int(time.time())}.png",  # unique filename
                        ContentFile(buffer.read()),
                        save=True
                    )
                    time.sleep(50)
                    captcha_input= driver.find_elements(By.CSS_SELECTOR, "div.input-group>input")
                    time.sleep(2)
                    captcha_input[2].click()
                    time.sleep(3)
                    captcha_input[2].send_keys(GLOBAL_CAPTCHA_VALUE)
                    login_button = driver.find_elements(By.CSS_SELECTOR,'button.mat-focus-indicator')
                    before_url = driver.current_url
                    # Click the login button
                    login_button[1].click()

                    # Wait for URL to change (meaning navigation occurred)
                    WebDriverWait(driver, 15).until(EC.url_changes(before_url))

                    # Optional: Add a brief wait to allow page content to load
                    time.sleep(2)

                    # Check again if URL really changed
                    after_url = driver.current_url
                    if after_url != before_url:
                        login_success = True
                        ScrapingStatus.objects.create(run=new_run, message="Captcha Solved Successfully")
                        break
                    
                except:
                    continue
            if not login_success:
                ScrapingStatus.objects.create(run=new_run, message="Login CAPTCHA solving failed after multiple attempts Try Again")
                driver.quit()
                return JsonResponse({"message": "Login CAPTCHA solving failed after multiple attempts."}, status=500)
            
            WebDriverWait(driver, 60).until(
                EC.presence_of_element_located((By.CSS_SELECTOR, 'h5.my-0')))
            search_certified = driver.find_elements(By.CSS_SELECTOR, 'li.ng-star-inserted>a')
            time.sleep(5)
            if len(search_certified) > 2:
                search_certified[2].click()
            else:
                driver.quit()
                return JsonResponse({"message": "Scraping failed: Initial elements not found."}, status=500)
            WebDriverWait(driver, 60).until(
                EC.presence_of_element_located((By.CSS_SELECTOR, 'div.apex-item-option')))
            
            # captch resolving   2
            captcha_success = False
            for retry in range(max_attempts):
                try:
                    driver.refresh()
                    time.sleep(10) 
                    other_details = driver.find_elements(By.CSS_SELECTOR, 'div.apex-item-option')
                    if len(other_details) > 2:
                        other_details[2].click()
                    else:
                        driver.quit()
                        return JsonResponse({"message": "Scraping failed: Other details elements not found."}, status=500)
                    
                    WebDriverWait(driver, 60).until(
                        EC.presence_of_element_located((By.CSS_SELECTOR, 'input#P2000_FROM_DATE')))
                    ScrapingStatus.objects.create(run=new_run, message="Filling District , Date , Deed Type")
                    period_from= driver.find_element(By.CSS_SELECTOR,"input#P2000_FROM_DATE")
                    period_from.click()
                    period_from.send_keys(date_from_fmt)
                    period_to= driver.find_element(By.CSS_SELECTOR,"input#P2000_TO_DATE")
                    period_to.send_keys(date_to_fmt)
                    WebDriverWait(driver, 60).until(
                        EC.presence_of_element_located((By.CSS_SELECTOR, 'select#P2000_DISTRICT')))
                    element = driver.find_element(By.CSS_SELECTOR, 'select#P2000_DISTRICT')
                    select_districts = Select(element)
                    select_districts.select_by_visible_text(district)
                    
                    time.sleep(5)
                    input_box = driver.find_element(By.XPATH, "//input[@aria-autocomplete='list']")
                    input_box.send_keys(deed_type)
                    time.sleep(5)
                    input_box.send_keys(Keys.ENTER)
                    time.sleep(10)
                    captcha= driver.find_elements(By.CSS_SELECTOR, "div.input-group>img")
                    captcha_img = captcha[1]
                    time.sleep(2)
                    driver.execute_script("arguments[0].scrollIntoView(true);", captcha_img)
                    time.sleep(2)
                    ScrapingStatus.objects.create(run=new_run, message="Trying To Solve Captcha-2")
                    dpr = driver.execute_script("return window.devicePixelRatio")
    
                    # Take full screenshot
                    screenshot_png = driver.get_screenshot_as_png()
                    image = Image.open(BytesIO(screenshot_png))
                    img_width, img_height = image.size
    
                    # Get CAPTCHA location and size
                    location = captcha_img.location_once_scrolled_into_view
                    size = captcha_img.size
    
                    # Calculate safe crop box
                    left = max(0, int(location['x'] * dpr))
                    top = max(0, int(location['y'] * dpr))
                    right = min(img_width, int((location['x'] + size['width']) * dpr))
                    bottom = min(img_height, int((location['y'] + size['height']) * dpr))
    
    
                    # Crop and save CAPTCHA
                    captcha_image = image.crop((left, top, right, bottom))
                    captcha_image.save("captcha_only.png")

                    buffer = BytesIO()
                    cropped_image.save(buffer, format="PNG")   # write the image into buffer
                    buffer.seek(0)  # rewind pointer

                    # Create status and attach the file
                    status = ScrapingStatus.objects.create(
                        run=new_run,
                        message="captcha_only.png"
                    )
                    status.captcha_image.save(
                        f"captcha_{int(time.time())}.png",  # unique filename
                        ContentFile(buffer.read()),
                        save=True
                    )
                    time.sleep(50)
                    captcha_input= driver.find_elements(By.CSS_SELECTOR, "div.input-group>input")
                    time.sleep(2)
                    captcha_input[1].click()
                    time.sleep(3)
                    captcha_input[1].send_keys(GLOBAL_CAPTCHA_VALUE)
                    time.sleep(3)
                    search_button = driver.find_elements(By.CSS_SELECTOR,'div>button.btn')
                    search_button[4].click()    
                    time.sleep(40)
                     # Wait for an element that only appears after login
                    WebDriverWait(driver, 15).until(
                        EC.presence_of_element_located((By.CSS_SELECTOR, "td.mat-cell>span.link"))  #  update if needed
                    )

                    login_success = True
                    ScrapingStatus.objects.create(run=new_run, message="Solved Successfully Captcha-2")

                    break
                except:
                    continue
            if not login_success:
                # update_status("Login CAPTCHA solving failed after multiple attempts Try Again")
                ScrapingStatus.objects.create(run=new_run, message="Login CAPTCHA solving failed after multiple attempts Try Again")

                driver.quit()
                return JsonResponse({"message": "Login CAPTCHA solving failed after multiple attempts."}, status=500)
                
            WebDriverWait(driver, 60).until(
                EC.presence_of_element_located((By.CSS_SELECTOR, 'td.mat-cell>span.link')))
            time.sleep(3)
            # arrow_button = driver.find_element(By.CSS_SELECTOR,'div.mat-select-arrow')
            # arrow_button.click()
            # time.sleep(2)

            # # select_50 = driver.find_elements(By.XPATH, "//mat-option[.//span[contains(text(), '50')]]")
            # # select_50.click()
            # # time.sleep(5)
            while True:  # Keep looping through all pages until no next button
                # Fetch all record links on current page
                data_elements = WebDriverWait(driver, 60).until(
                    EC.presence_of_all_elements_located((By.CSS_SELECTOR, 'td.mat-cell>span.link'))
                )

                for i in range(len(data_elements)):
                    # Re-locate elements each time (important after navigation)
                    data_elements_2 = WebDriverWait(driver, 60).until(
                        EC.presence_of_all_elements_located((By.CSS_SELECTOR, 'td.mat-cell>span.link'))
                    )

                    if i < len(data_elements_2):
                        span = data_elements_2[i]
                        driver.execute_script("arguments[0].click();", span)  # safer than normal click
                        time.sleep(5)
                        ScrapingStatus.objects.create(run=new_run, message=f"Try In Fetch Data Of Page {i}")
                        Registration_details_data = driver.find_elements(By.XPATH, "//fieldset[legend[contains(text(), 'Registration Details')]]/div/table/tbody/tr/td")
                        Registration_details_heading = driver.find_elements(By.XPATH, "//fieldset[legend[contains(text(), 'Registration Details')]]/div/table/thead/tr/th")
                        headings = [th.text.strip() for th in Registration_details_heading]
                        data_texts = [td.text.strip() for td in Registration_details_data]

                        # Extract Seller
                        seller_data = driver.find_elements(By.XPATH, '//fieldset[legend[contains(text(), "Party From")]]/div/table/tbody/tr/td')
                        seller_heading = driver.find_elements(By.XPATH, "//fieldset[legend[contains(text(), 'Party From')]]/div/table/thead/tr/th")
                        headings_2 = [th.text.strip() for th in seller_heading]
                        data_texts_2 = [td.text.strip() for td in seller_data]

                        # Extract Buyer
                        buyer_data = driver.find_elements(By.XPATH, "//fieldset[legend[contains(text(), 'Party To')]]/div/table/tbody/tr/td")
                        buyer_heading = driver.find_elements(By.XPATH, "//fieldset[legend[contains(text(), 'Party To')]]/div/table/thead/tr/th")
                        headings_3 = [th.text.strip() for th in buyer_heading]
                        data_texts_3 = [td.text.strip() for td in buyer_data]

                        # Extract Property Details
                        property_details = driver.find_elements(By.XPATH, "//fieldset[legend[contains(text(), 'Property Details')]]/div/table/tbody/tr/td")
                        property_heading = driver.find_elements(By.XPATH, "//fieldset[legend[contains(text(), 'Property Details')]]/div/table/thead/tr/th")
                        headings_4 = [th.text.strip() for th in property_heading]
                        data_texts_4 = [td.text.strip() for td in property_details]

                        # Extract Khasra/Building/Plot Details
                        khasra_building_plot_details = driver.find_elements(By.XPATH, "//fieldset[legend[contains(text(), 'Khasra/Building/Plot Details')]]/div/table/tbody/tr/td")
                        khasra_heading = driver.find_elements(By.XPATH, "//fieldset[legend[contains(text(), 'Khasra/Building/Plot Details')]]/div/table/thead/tr/th")
                        headings_5 = [th.text.strip() for th in khasra_heading]
                        data_texts_5 = [td.text.strip() for td in khasra_building_plot_details]

                        # Parse address inside property details
                        final_data_texts_4 = []
                        for heading_100, data in zip(headings_4, data_texts_4):
                            if "address" in heading_100.lower():
                                parsed_addr = parse_address(data)
                                for k, v in parsed_addr.items():
                                    final_data_texts_4.append((k, v))
                            else:
                                final_data_texts_4.append((heading_100, data))

                        headings_4_parsed = [h for h, v in final_data_texts_4]
                        data_texts_4_parsed = [v for h, v in final_data_texts_4]

                        all_sections = [
                            (headings, data_texts),
                            (headings_2, data_texts_2),
                            (headings_3, data_texts_3),
                            (headings_4_parsed, data_texts_4_parsed),
                            (headings_5, data_texts_5),
                        ]

                        # Save to Excel
                        save_to_db(all_sections)

                        # Close popup
                        try:
                            data_elements_200 = WebDriverWait(driver, 60).until(
                                EC.presence_of_all_elements_located((By.CSS_SELECTOR, 'button.colsebtn'))
                            )
                            if len(data_elements_200) > 1:
                                data_elements_200[1].click()
                            else:
                                data_elements_200[0].click()
                            time.sleep(3)
                        except:
                            print("Close button not found")
                    else:
                        break

                # --- Pagination Part ---
                try:
                    next_button = driver.find_element(By.CSS_SELECTOR, "button.mat-paginator-navigation-next")
                    if "disabled" in next_button.get_attribute("class"):
                        break
                    else:
                        driver.execute_script("arguments[0].click();", next_button)
                        time.sleep(5)
                except:
                    break
            ScrapingStatus.objects.create(run=new_run, message="Scraping completed successfully! Check sampada_data please Download file by moving to http://127.0.0.1:8000/get-status/")
            return JsonResponse({"message": f"Scraping completed successfully! Check sampada_data{timestamp_2}.xlsx"})


        except Exception as e:
            print(f"An error occurred during scraping: {e}")
            ScrapingStatus.objects.create(run=new_run, message="Scraping Failded Some Error is There please Try Again")
            return JsonResponse({"message": f"Scraping failed: {e}"}, status=500)
        finally:
            driver.quit()

    return render(request, 'scraper_app/scrape_form.html')

    
def clear_logs(request):
    ScrapingStatus.objects.all().delete()
    return JsonResponse({"message": "Logs cleared"})

def download_excel(request):
    records = ScrapedRecord.objects.all()
    wb = Workbook()
    ws = wb.active

    # Create headers dynamically from first record
    if records.exists():
        first = records.first()
        headers = list(first.registration_details.keys()) + \
                  list(first.seller_details.keys()) + \
                  list(first.buyer_details.keys()) + \
                  list(first.property_details.keys()) + \
                  list(first.khasra_details.keys())
        ws.append(headers)

        for r in records:
            row = list(r.registration_details.values()) + \
                  list(r.seller_details.values()) + \
                  list(r.buyer_details.values()) + \
                  list(r.property_details.values()) + \
                  list(r.khasra_details.values())
            ws.append(row)

    # Prepare response
    response = HttpResponse(
        content_type='application/vnd.openxmlformats-officedocument.spreadsheetml.sheet',
    )
    response['Content-Disposition'] = 'attachment; filename="scraped_data.xlsx"'
    wb.save(response)
    return response

GLOBAL_CAPTCHA_VALUE = None 
def show_captcha(request):
    global GLOBAL_CAPTCHA_VALUE
    latest_status = ScrapingStatus.objects.order_by("-created_at").first()
    captcha_value = None

    if request.method == "POST":
        captcha_value = request.POST.get("captcha_value")
        GLOBAL_CAPTCHA_VALUE = captcha_value  # store globally
        print("🔹 Received Captcha:", captcha_value)

        # do something with captcha_value before re-render
    
    return render(
        request,
        "scraper_app/solve_captchas.html",
        {"status": latest_status,"captcha_value": captcha_value},
    )


