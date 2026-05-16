import json

with open('d:/repository/browser_template/source.ipynb', 'r', encoding='utf-8') as f:
    nb = json.load(f)

cells_to_keep = nb['cells'][:8]

new_source = """from utils.recaptcha_solver_v3 import RecaptchaSolver
import asyncio

async def solve_and_confirm(page, solver, max_retries=3):
    for attempt in range(max_retries):
        try:
            await solver.solveCaptcha()
            
            # Solved -> click OK
            await page.click("button.c-button--primary")
            print("[INFO] Clicked OK")
            return True
            
        except Exception as e:
            print(f"[WARN] Attempt {attempt+1} failed: {e}")
            
            if attempt < max_retries - 1:
                await page.reload()
                await page.wait_for_timeout(2000)
                print(f"[INFO] Retrying... ({attempt+2}/{max_retries})")
    
    return False

# Loop over retailers
for retailer in retailer_list:
    retailer_id = retailer['retailer_id']
    url = f"https://shop.11st.co.kr/m/{retailer_id}/info"
    print(f"\\n=========================================")
    print(f"[INFO] Processing retailer: {retailer_id}")
    print(f"=========================================")
    
    try:
        await page.goto(url)
        await page.wait_for_load_state("load")
        
        # Click to show info
        has_button = await page.evaluate('''
            window.open = (url) => { window.location.href = url; };
            let btn = document.querySelector('[data-ui-type="Store_Info_Offline"] button');
            if (btn) {
                btn.click();
                return true;
            }
            return false;
        ''')
        
        if has_button:
            print("[INFO] Clicked info button, checking for captcha...")
            await page.wait_for_timeout(3000)
            
            solver = RecaptchaSolver(page)
            success = await solve_and_confirm(page, solver)
            
            if success:
                print(f"[SUCCESS] Captcha solved for {retailer_id}")
                await page.wait_for_timeout(3000)
                
                # TODO: Scrape data here
                
            else:
                print(f"[FAILED] Could not solve captcha for {retailer_id}")
        else:
            print(f"[INFO] No info button found for {retailer_id}. Maybe no captcha needed?")
            # TODO: Scrape data directly here if no button
            
    except Exception as e:
        print(f"[ERROR] Failed to process {retailer_id}: {e}")
        
    await page.wait_for_timeout(2000)
"""

lines = new_source.split('\n')
source_lines = [line + '\n' for line in lines[:-1]] + [lines[-1]]

new_cell = {
    'cell_type': 'code',
    'execution_count': None,
    'id': 'combined_scrape_task',
    'metadata': {},
    'outputs': [],
    'source': source_lines
}

cells_to_keep.append(new_cell)
nb['cells'] = cells_to_keep

with open('d:/repository/browser_template/source.ipynb', 'w', encoding='utf-8') as f:
    json.dump(nb, f, indent=1)

print("Notebook updated successfully.")
