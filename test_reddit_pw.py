from playwright.sync_api import sync_playwright

with sync_playwright() as p:
    browser = p.chromium.launch(headless=True)
    page = browser.new_page()
    page.goto('https://old.reddit.com/r/MemesBR/hot/')
    posts = page.locator('.thing').all()
    for post in posts[:3]:
        title = post.locator('.title > a.title').text_content()
        url = post.locator('.title > a.title').get_attribute('href')
        print(f"Title: {title}, URL: {url}")
    browser.close()
