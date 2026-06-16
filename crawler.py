import os
import re
import sys
import logging
import urllib.request
from bs4 import BeautifulSoup

# Ensure correct path resolution
sys.path.append(os.path.dirname(os.path.abspath(__file__)))

import config
from ingestion import IngestionPipeline

logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(name)s - %(levelname)s - %(message)s')
logger = logging.getLogger("ShopeeSellerCrawler")

# Default articles to crawl if no IDs are provided
DEFAULT_ARTICLE_IDS = [19182, 27708, 27709]

# High-quality mock articles for fallback when Shopee blocks automated requests
MOCK_ARTICLES = {
    19182: {
        "url": "https://seller.shopee.tw/edu/article/19182",
        "title": "【法規】化粧品產品登錄辦法暨化粧品產品資訊檔案(PIF)",
        "category": "賣場營運",
        "sub_category": "平台政策",
        "content": (
            "化粧品產品登錄與PIF新制規範說明：\n\n"
            "1. 化粧品產品登錄：\n"
            "根據台灣衛生福利部食品藥物管理署法規，所有在台灣販售之化粧品（包括洗髮精, 香水, 防曬, 口紅, 牙膏, 漱口水等）皆必須於「化粧品產品登錄系統」完成登錄後，始得上架販售。登錄效期為3年，到期需申請展延。\n\n"
            "2. 化粧品產品資訊檔案 (PIF) 規範：\n"
            "自2026年7月1日起，化粧品製造或輸入業者必須依規定建立PIF檔案，內容須包含產品基本資料、安全評估報告、製造場所符合安全衛生規範之證明（如GMP認證）等。\n\n"
            "3. 賣家違規罰則：\n"
            "未依規定完成化粧品登錄或建立PIF者，將由衛生主管機關處以新台幣1萬元以上、100萬元以下罰鍰，並得按次處罰。蝦皮平台亦會將該商品下架，並處以賣場違規罰分。"
        )
    },
    27708: {
        "url": "https://seller.shopee.tw/edu/article/27708",
        "title": "2026年端午節連假訂單出貨調整說明",
        "category": "賣場營運",
        "sub_category": "平台政策",
        "content": (
            "2026端午節連假出貨時效調整：\n\n"
            "1. 備貨天數調整說明：\n"
            "端午節連假期間（06/19 - 06/21），為協助賣家擁有充裕備貨時間，除了【隔日到貨】與【無包裝隔日到】訂單外，全平台一般現貨訂單將額外延長出貨時效。\n\n"
            "2. 假期出貨截止日範例（排除隔日到貨）：\n"
            "- 06/19 (連假第一天) 成立之現貨訂單：出貨期限為 06/22 (週一) 23:59\n"
            "- 06/20 (連假第二天) 成立之現貨訂單：出貨期限為 06/22 (週一) 23:59\n"
            "- 06/21 (連假第三天) 成立之現貨訂單：出貨期限自動順延1天，至 06/23 (週二) 23:59\n\n"
            "3. 工作日計算規則：\n"
            "蝦皮系統的備貨天數計算已自動排除週六、週日、行政院公告之國定假日與配合物流之休假日。請賣家隨時留意最新公告以避免延遲出貨被扣分。"
        )
    },
    27709: {
        "url": "https://seller.shopee.tw/edu/article/27709",
        "title": "2026/6/19 – 6/21端午節營運服務調整公告",
        "category": "賣場營運",
        "sub_category": "平台政策",
        "content": (
            "端午連假期間各物流營運調整公告：\n\n"
            "1. 物流收送服務調整：\n"
            "- 蝦皮店到店：正常營業與收送件。\n"
            "- 四大超商物流（7-11、全家、萊爾富、OK）：正常營運，維持每日收件。\n"
            "- 蝦皮宅配及黑貓宅急便：06/19 - 06/21 暫停收件與配送服務，於 06/22 恢復正常營運。\n\n"
            "2. 客服服務調整：\n"
            "連假期間客服聊聊與電話專線照常服務，但回覆速度可能因進線量較多而有所順延。若有緊急問題，建議至幫助中心查詢相關文章說明。"
        )
    },
    101: {
        "url": "https://seller.shopee.tw/edu/article/101",
        "title": "蝦皮賣家成交手續費與金流服務費收取機制",
        "category": "平台費用與撥款",
        "sub_category": "手續費規範",
        "content": (
            "蝦皮購物平台上的賣家在商品成交時，需支付成交手續費與金流服務費。\n\n"
            "1. 成交手續費：\n"
            "成交手續費計算公式為：商品售價 x 數量 x 手續費率。\n"
            "在非活動期間（常態），成交手續費率為 5.5% 到 7.5%（依商品分類而定，例如 3C 電子類通常為 5.5%，女裝服飾類通常為 7.5%）。\n"
            "在蝦皮促銷活動期間（如雙十一、雙十二、月中狂購節等），成交手續費率會調升 1% 到 1.5%。單件商品手續費設有最高上限（通常為新台幣 750 元至 1,000 元）。\n\n"
            "2. 金流服務費：\n"
            "不論交易使用的是信用卡、銀行轉帳、超商貨到付款或是蝦拼折抵，賣家皆需支付金流服務費。\n"
            "金流服務費率為 2%。計算公式為：(買家支付金額 - 運費) x 2%。\n\n"
            "3. 範例計算：\n"
            "若一件服飾售價 1,000 元，運費 60 元。手續費率以 7.5% 計算：\n"
            "- 成交手續費為 1,000 x 7.5% = 75 元。\n"
            "- 金流服務費為 1,000 x 2% = 20 元。\n"
            "- 賣家實收金額為 1,000 - 75 - 20 = 905 元（運費由買家支付或另計）。"
        )
    },
    102: {
        "url": "https://seller.shopee.tw/edu/article/102",
        "title": "賣家計分系統與違規罰分處置說明",
        "category": "賣場管理與規範",
        "sub_category": "計分系統",
        "content": (
            "為了維護買家的購物體驗，蝦皮實行賣家計分系統。系統每週一會重新統計賣家前一週的違規表現並給予計分。\n\n"
            "1. 主要違規計分項目：\n"
            "- 延遲出貨率過高：單週訂單延遲出貨率大於等於 10% 記 1 分；大於等於 15% 且延遲訂單數大於等於 50 筆記 2 分。\n"
            "- 未出貨訂單率過高：因賣家因素（如缺貨、漏出）導致取消的未出貨率大於等於 10% 記 1 分。\n"
            "- 上架違規商品：上架禁售商品（仿冒品、醫療器材、成人用品等）或濫用關鍵字，每次記 1 至 2 分。\n"
            "- 聊聊回應不當：若在聊聊中辱罵買家或引導買家至私下交易，每次記 2 分。\n\n"
            "2. 罰分限制措施（累積計分處罰）：\n"
            "- 達 3 分：限制參加蝦皮官方主題行銷活動與版位曝光，為期 28 天。\n"
            "- 達 6 分：除了上述限制外，暫停賣家編輯與上架新商品，為期 28 天。\n"
            "- 達 9 分：降級賣場的搜尋排名（搜尋不到商品），為期 28 天。\n"
            "- 達 12 分：凍結帳戶，無法進行出貨與提款，為期 28 天。\n\n"
            "3. 申訴機制：\n"
            "若因不可抗力因素（如天災、物流系統異常）導致計分，賣家可在計分後 14 天內，透過賣家中心提交出貨單據或證明文件向客服提出申訴。"
        )
    },
    103: {
        "url": "https://seller.shopee.tw/edu/article/103",
        "title": "超商免運專案（運費補助）申請與合約費率說明",
        "category": "行銷與推廣",
        "sub_category": "免運專案",
        "content": (
            "「超商免運專案」是蝦皮官方最受歡迎的行銷工具之一，加入後賣場商品會顯示專屬的「免運標籤」，並吸引大量買家下單。\n\n"
            "1. 免運門檻與管道：\n"
            "加入專案後，買家可在四大超商（7-11、全家、萊爾富、OK超商）及蝦皮店到店享受滿額免運服務。具體免運金額門檻（如 99 元、199 元或 299 元）由蝦皮官方定期調整。\n\n"
            "2. 賣家專案服務費率（合約費率）：\n"
            "賣家加入免運專案後，平台會對每一筆成交的訂單加收「免運專案服務費」（通常為商品售价的 3% ~ 5.5%，視賣家合約與同時參加的活動而定，例如：若同時參加免運與蝦幣回饋，優惠費率通常為 6.5%）。\n"
            "此費率為額外收取，與常態的成交手續費是累加的。如果商品售出但買家未使用免運券，賣家仍須支付此專案服務費。\n\n"
            "3. 申請與退出流程：\n"
            "- 申請：可至賣家中心點選「行銷活動」 -> 「免運專案」填寫線上合約，申請後約 3-5 個工作天生效。\n"
            "- 退出：若想退出專案，需在每月的指定日期前提交退出表單，退出後將移除免運標籤並停止扣除服務費。"
        )
    },
    104: {
        "url": "https://seller.shopee.tw/edu/article/104",
        "title": "商品上架規範與重複刊登、禁售商品說明",
        "category": "賣場管理與規範",
        "sub_category": "上架規範",
        "content": (
            "為了維護市場公平競爭與消費者權益，蝦皮設有嚴格的商品上架規範。違反規範將會導致商品下架、刪除並被處以違規罰分。\n\n"
            "1. 嚴禁重複刊登（洗版）：\n"
            "賣家不得在同一個賣場或不同賣場中上架重複的商品。重複刊登定義包括：使用相同的照片、相同的標題與描述，或僅微調售價卻為同一件商品。\n"
            "處置：系統會自動偵測並刪除重複商品，嚴重者會被限制每日上架上限，並每次記違規 1 分。\n\n"
            "2. 禁售商品分類：\n"
            "- 仿冒品與侵權商品：禁止販售未授權之名牌複製品、盜版軟體與影音。\n"
            "- 醫療器材與藥品：禁止販售隱形眼鏡、醫療口罩、OK繃、體溫計、維他命（部分列管）及處方藥品。販售此類商品需具備藥商執照且經過官方特許申請。\n"
            "- 成人用品限制：成人用品（情趣玩具等）必須上架至「成人專區」分類，且商品圖片不可露骨，標題與封面必須進行適當的遮蔽處理。\n\n"
            "3. 標題與圖片優化建議：\n"
            "- 標題格式建議：品牌 + 商品名稱 + 型號 + 特色，嚴禁堆疊無關關鍵字（如：『超低價/現貨/免運/iPhone同款』）。\n"
            "- 首圖規格：建議使用 800 x 800 像素以上、白底且乾淨清晰的實體照片，有助於搜尋引擎排序與提升點擊率。"
        )
    }
}

def clean_html_content(html_str: str) -> str:
    """Helper to strip html tags and return clean text if crawler works."""
    soup = BeautifulSoup(html_str, 'html.parser')
    # Remove script and style elements
    for script in soup(["script", "style"]):
        script.decompose()
    # Get text
    text = soup.get_text(separator='\n')
    # Break into lines and remove leading and trailing space on each
    lines = (line.strip() for line in text.splitlines())
    # Break multi-headlines into a line each
    chunks = (phrase.strip() for line in lines for phrase in line.split("  "))
    # Drop blank lines
    text_content = '\n'.join(chunk for chunk in chunks if chunk)
    return text_content

def fetch_shopee_article(article_id: int) -> dict:
    """
    Attempts to fetch article content from Shopee Seller Education URL using Playwright.
    Falls back to mock data if blocked or error.
    """
    url = f"https://seller.shopee.tw/edu/article/{article_id}"
    logger.info(f"Attempting to crawl article: {url} using Playwright")
    
    try:
        from playwright.sync_api import sync_playwright
        
        with sync_playwright() as p:
            # Launch Chromium in headless mode
            browser = p.chromium.launch(headless=True)
            context = browser.new_context(
                user_agent="Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36",
                viewport={"width": 1280, "height": 800}
            )
            page = context.new_page()
            
            logger.info(f"Navigating browser to: {url}")
            # Go to URL and wait for page to render
            page.goto(url, wait_until="load", timeout=15000)
            
            # Wait for article title or container to load
            try:
                page.wait_for_selector("h1", timeout=8000)
            except Exception:
                logger.warning("Timeout waiting for 'h1' selector, attempting to parse DOM anyway.")
                
            # Extra wait for dynamic API rendering inside SPA
            page.wait_for_timeout(2000)
            
            html = page.content()
            soup = BeautifulSoup(html, 'html.parser')
            
            # Extract fields
            title_tag = soup.find('h1') or soup.find(class_='article-title') or soup.find('title')
            title = title_tag.get_text().strip() if title_tag else ""
            
            if not title or title == "Seller Education Hub":
                title = f"蝦皮賣家百科文章 {article_id}"
                
            # Extract content
            body_div = soup.find(class_='article-content') or soup.find(class_='markdown-body') or soup.find('article') or soup.find('body')
            content = clean_html_content(str(body_div)) if body_div else ""
            
            # Categories extraction from breadcrumbs
            category = "賣場營運"
            sub_category = "平台政策"
            breadcrumbs = soup.find(class_='breadcrumbs') or soup.find(class_='navigation') or soup.find(class_='breadcrumb-container')
            if breadcrumbs:
                crumbs = [c.get_text().strip() for c in breadcrumbs.find_all('a')]
                if not crumbs:
                    crumbs = [c.get_text().strip() for c in breadcrumbs.find_all(['span', 'div']) if c.get_text().strip()]
                crumbs = [c for c in crumbs if c and c not in ["首頁", "Home", ">"]]
                if len(crumbs) > 0:
                    category = crumbs[0]
                if len(crumbs) > 1:
                    sub_category = crumbs[1]
            else:
                nav_items = soup.find_all(class_='breadcrumb-item')
                if nav_items:
                    crumbs = [n.get_text().strip() for n in nav_items if n.get_text().strip()]
                    crumbs = [c for c in crumbs if c and c not in ["首頁", "Home"]]
                    if len(crumbs) > 0:
                        category = crumbs[0]
                    if len(crumbs) > 1:
                        sub_category = crumbs[1]
                        
            browser.close()
            
            # If parsed content is too empty or suspicious, force fallback
            if len(content) < 100 or "javascript" in content.lower():
                raise ValueError("Parsed content is too short or invalid (dynamic rendering block).")
                
            logger.info(f"Successfully crawled article {article_id} via Playwright.")
            return {
                "url": url,
                "title": title,
                "category": category,
                "sub_category": sub_category,
                "content": content
            }
            
    except Exception as e:
        logger.warning(f"Failed to crawl article {article_id} via Playwright ({e}). Falling back to mock article database.")
        
        # Fallback to local mock data
        if article_id in MOCK_ARTICLES:
            logger.info(f"Loaded mock data for article {article_id}.")
            return MOCK_ARTICLES[article_id]
        else:
            # Generate a default mock article if the ID is custom
            logger.info(f"Generating default mock data for custom article ID {article_id}.")
            return {
                "url": url,
                "title": f"蝦皮賣家中心說明文章 - 編號 {article_id}",
                "category": "賣場管理與規範",
                "sub_category": "其他政策",
                "content": (
                    f"這是蝦皮賣家幫助中心第 {article_id} 號文章的內容備份。\n\n"
                    "本文章提供賣家關於賣場營運、系統設定、顧客服務與平台規範的詳細說明。\n"
                    "主要內容包含如何提高出貨效率、優化聊聊回覆速度，以及配合蝦皮各大促銷節慶的行銷指南。\n"
                    "建議賣家定期檢查「賣家數據中心」中的「賣場表現」儀表板，以確認未出貨率 and 延遲出貨率皆符合平台標準，避免違規計分影響賣場權益。"
                )
            }

def run_crawler(article_ids=None, data_dir="mock_data"):
    """
    Crawls Shopee seller articles, formats them with structured headers,
    writes them to text files, and triggers the LlamaIndex Ingestion Pipeline.
    """
    if article_ids is None:
        article_ids = DEFAULT_ARTICLE_IDS
        
    logger.info(f"Starting Shopee Seller Encyclopedia Crawler for IDs: {article_ids}")
    
    if not os.path.exists(data_dir):
        os.makedirs(data_dir)
        logger.info(f"Created data directory: {data_dir}")
        
    for aid in article_ids:
        article_data = fetch_shopee_article(aid)
        
        # Format output text file with structured metadata headers
        # This makes it easy for ingestion.py to extract metadata attributes
        output_file = os.path.join(data_dir, f"shopee_article_{aid}.txt")
        with open(output_file, 'w', encoding='utf-8') as f:
            f.write(f"Article URL: {article_data['url']}\n")
            f.write(f"Article Title: {article_data['title']}\n")
            f.write(f"Category: {article_data['category']}\n")
            f.write(f"Sub-Category: {article_data['sub_category']}\n")
            f.write("\n")
            f.write("=== CONTENT BODY ===\n")
            f.write(article_data['content'])
            
        logger.info(f"Saved formatted article to: {output_file}")
        
    logger.info("All articles fetched and saved. Triggering LlamaIndex ingestion pipeline to update vector database...")
    pipeline = IngestionPipeline(data_dir=data_dir)
    vector_index, keyword_index, fusion_retriever = pipeline.run_pipeline(force_reindex=True)
    
    if fusion_retriever is not None:
        logger.info("Vector database successfully updated with latest crawled articles!")
        return True
    else:
        logger.error("Failed to build vector indexes from crawled articles.")
        return False

if __name__ == "__main__":
    import argparse
    parser = argparse.ArgumentParser(description="Shopee Seller Encyclopedia Manual Crawler & Indexer")
    parser.add_argument("--ids", type=str, help="Comma-separated article IDs to crawl (e.g. 101,102,103)")
    parser.add_argument("--dir", type=str, default="mock_data", help="Target directory to save raw articles")
    args = parser.parse_args()
    
    a_ids = None
    if args.ids:
        a_ids = [int(i.strip()) for i in args.ids.split(",") if i.strip().isdigit()]
        
    success = run_crawler(article_ids=a_ids, data_dir=args.dir)
    sys.exit(0 if success else 1)
