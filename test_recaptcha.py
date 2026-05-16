import asyncio
import logging
from playwright_handler import PlaywrightHandler
from utils.recaptcha_solver import RecaptchaSolver, CapMonsterSolver

# Set your API Key here if using a service
CAPMONSTER_API_KEY = "" 

async def test_solver():
    logging.basicConfig(level=logging.INFO)
    
    async with PlaywrightHandler(headless=False) as handler:
        page = await handler.get_page()
        
        logging.info("Navigating to reCAPTCHA demo page...")
        await page.goto("https://www.google.com/recaptcha/api2/demo")
        
        if CAPMONSTER_API_KEY:
            logging.info("Using CapMonster Service...")
            solver = CapMonsterSolver(page, CAPMONSTER_API_KEY)
            # site key extraction is automatic
            success = await solver.solve(submit_button_selector="#recaptcha-demo-submit")
        else:
            logging.info("Using Audio Bypass Method...")
            solver = RecaptchaSolver(page)
            success = await solver.solve()
            if success:
                await page.click("#recaptcha-demo-submit")
        
        if success:
            logging.info("reCAPTCHA process completed!")
            await page.wait_for_timeout(3000)
            content = await page.content()
            if "Verification Success" in content:
                logging.info("Demo form submitted successfully!")
        else:
            logging.error("Failed to solve reCAPTCHA.")

if __name__ == "__main__":
    asyncio.run(test_solver())
