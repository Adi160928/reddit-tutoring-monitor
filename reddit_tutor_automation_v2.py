import praw
import google.generativeai as genai
import pandas as pd
from datetime import datetime, timedelta
import time
import os
from dotenv import load_dotenv

# Load environment variables
load_dotenv()

# ==================== CONFIGURATION ====================

# Reddit API Credentials (loaded from .env file)
REDDIT_CONFIG = {
    "client_id": os.getenv("REDDIT_CLIENT_ID"),
    "client_secret": os.getenv("REDDIT_CLIENT_SECRET"), 
    "user_agent": os.getenv("REDDIT_USER_AGENT")
}

# Gemini API Key (loaded from .env file)
GEMINI_API_KEY = os.getenv("GEMINI_API_KEY")

# Target Subreddits (Customize based on your geography)
TARGET_SUBREDDITS = [
    "tutoring",
    "HomeworkHelp", 
    "learnmath",
    "askmath",
    "MathHelp",
    "APStudents",
    "GCSE",
    "6thForm",
    "igcse",
    "IBO",
    # Add location-specific: "bangalore", "india", "mumbai", "UKParenting" etc.
]

# Search Keywords
KEYWORDS = [
    "math tutor",
    "mathematics tutor",
    "maths help",
    "need math help",
    "looking for tutor",
    "algebra help",
    "calculus tutor",
    "geometry tutor",
    "statistics help",
    "maths teacher",
    "online tutor"
]

# Grade Level Keywords
GRADE_KEYWORDS = {
    "elementary": ["year 2", "year 3", "year 4", "year 5", "year 6", "primary", "elementary", "grade 2", "grade 3", "grade 4", "grade 5"],
    "middle": ["year 7", "year 8", "year 9", "middle school", "gcse", "grade 6", "grade 7", "grade 8"],
    "high": ["year 10", "year 11", "year 12", "year 13", "a-level", "a level", "high school", "igcse", "ib", "grade 9", "grade 10", "grade 11", "grade 12"]
}

# Your Tutor Profile (CUSTOMIZE THIS!)
TUTOR_PROFILE = """
- 2 years of online mathematics tutoring experience
- Teach students from Year 2 to Year 12
- Specialize in building strong fundamentals and exam preparation
- Experience with GCSE, IGCSE, A-Level, and IB curriculum
- Online sessions via Zoom/Google Meet
- Free 20-minute trial session available
- Book trial: [YOUR CALENDLY LINK or WhatsApp: +91-XXXXXXXXXX]
"""

# ==================== REDDIT SCRAPER ====================

class RedditLeadFinder:
    def __init__(self):
        self.reddit = praw.Reddit(**REDDIT_CONFIG)
        self.leads = []
        self.processed_ids = self.load_processed_ids()

    def load_processed_ids(self):
        """Load previously processed post IDs to avoid duplicates"""
        try:
            df = pd.read_csv('processed_leads.csv')
            return set(df['post_id'].tolist())
        except FileNotFoundError:
            return set()

    def search_posts(self, hours_back=24):
        """Search for relevant tutoring posts in last X hours"""
        print(f"🔍 Searching posts from last {hours_back} hours...\n")

        cutoff_time = datetime.now() - timedelta(hours=hours_back)

        for subreddit_name in TARGET_SUBREDDITS:
            try:
                subreddit = self.reddit.subreddit(subreddit_name)

                # Search new posts
                for post in subreddit.new(limit=50):
                    # Skip already processed posts
                    if post.id in self.processed_ids:
                        continue

                    post_time = datetime.fromtimestamp(post.created_utc)

                    if post_time < cutoff_time:
                        continue

                    # Check if post matches keywords
                    post_text = (post.title + " " + post.selftext).lower()

                    if any(keyword in post_text for keyword in KEYWORDS):
                        lead_data = self.extract_lead_data(post)
                        if lead_data:
                            self.leads.append(lead_data)
                            self.processed_ids.add(post.id)
                            print(f"✅ Found lead: {post.title[:60]}...")

                time.sleep(2)  # Rate limiting

            except Exception as e:
                print(f"⚠️  Error in r/{subreddit_name}: {str(e)}")

        print(f"\n📊 Total NEW leads found: {len(self.leads)}\n")
        return self.leads

    def extract_lead_data(self, post):
        """Extract relevant information from post"""
        post_text = (post.title + " " + post.selftext).lower()

        # Determine grade level
        grade_level = self.detect_grade_level(post_text)

        # Detect urgency
        urgency_keywords = ["urgent", "asap", "exam tomorrow", "test tomorrow", "due tomorrow", "help now", "need help now"]
        is_urgent = any(keyword in post_text for keyword in urgency_keywords)

        # Detect if parent or student
        is_parent = any(word in post_text for word in ["my son", "my daughter", "my child", "my kid", "my children"])

        # Extract topics mentioned
        topics = self.extract_topics(post_text)

        # Check if they mention budget/payment
        mentions_payment = any(word in post_text for word in ["pay", "rate", "price", "cost", "budget", "hourly", "per hour"])

        return {
            "post_id": post.id,
            "subreddit": post.subreddit.display_name,
            "title": post.title,
            "content": post.selftext,
            "author": str(post.author),
            "url": f"https://reddit.com{post.permalink}",
            "created_utc": datetime.fromtimestamp(post.created_utc).strftime("%Y-%m-%d %H:%M"),
            "grade_level": grade_level,
            "is_urgent": is_urgent,
            "is_parent": is_parent,
            "topics": ", ".join(topics),
            "mentions_payment": mentions_payment,
            "score": post.score,
            "num_comments": post.num_comments,
            "priority_score": 0,  # Will be calculated later
            "generated_message": "",
            "status": "New",
            "response_received": "No",
            "notes": ""
        }

    def detect_grade_level(self, text):
        """Detect student grade level from post"""
        for level, keywords in GRADE_KEYWORDS.items():
            if any(keyword in text for keyword in keywords):
                return level
        return "unknown"

    def extract_topics(self, text):
        """Extract specific math topics mentioned"""
        topics = []
        topic_keywords = {
            "algebra": ["algebra", "equation", "variable", "expression", "quadratic"],
            "calculus": ["calculus", "derivative", "integral", "limit", "differentiation"],
            "geometry": ["geometry", "triangle", "circle", "angle", "polygon"],
            "trigonometry": ["trigonometry", "sine", "cosine", "trig", "tan"],
            "statistics": ["statistics", "probability", "mean", "median", "data"],
            "arithmetic": ["addition", "subtraction", "multiplication", "division", "fractions", "decimals"]
        }

        for topic, keywords in topic_keywords.items():
            if any(keyword in text for keyword in keywords):
                topics.append(topic)

        return topics if topics else ["general mathematics"]

# ==================== GEMINI PERSONALIZATION ====================

class GeminiMessageGenerator:
    def __init__(self, api_key):
        genai.configure(api_key=api_key)
        self.model = genai.GenerativeModel('gemini-pro')

    def generate_personalized_message(self, lead_data):
        """Generate personalized outreach message using Gemini"""

        prompt = f"""
You are a professional mathematics tutor writing a personalized, helpful response to a Reddit post.

TUTOR PROFILE:
{TUTOR_PROFILE}

POST DETAILS:
- Subreddit: r/{lead_data['subreddit']}
- Title: {lead_data['title']}
- Content: {lead_data['content']}
- Grade Level: {lead_data['grade_level']}
- Urgent: {lead_data['is_urgent']}
- Posted by: {"Parent" if lead_data['is_parent'] else "Student"}
- Topics: {lead_data['topics']}

INSTRUCTIONS:
1. Write a personalized, conversational Reddit comment (150-200 words)
2. Reference specific details from their post (quote a phrase if relevant)
3. Demonstrate expertise by offering one helpful tip or insight related to their problem
4. Keep tone friendly and supportive (match whether parent or student)
5. Mention your tutoring experience naturally (don't sound salesy)
6. Offer a free 20-minute trial session
7. End with a simple call-to-action (DM for details or reply)
8. DO NOT sound templated or robotic
9. DO NOT use overly formal language - be conversational
10. Make it feel genuinely helpful first, promotional second
11. Use Reddit-style formatting (no emojis unless natural)

Generate ONLY the message, no additional commentary:
"""

        try:
            response = self.model.generate_content(prompt)
            return response.text.strip()
        except Exception as e:
            return f"Error generating message: {str(e)}"

# ==================== LEAD SCORING ====================

def score_lead(lead):
    """Score lead quality (1-10)"""
    score = 5  # Base score

    # Urgent posts score higher
    if lead['is_urgent']:
        score += 2

    # Posts with specific topics score higher
    if len(lead['topics'].split(", ")) > 1:
        score += 1

    # Parent posts often more serious
    if lead['is_parent']:
        score += 1

    # Mentions payment = serious buyer
    if lead['mentions_payment']:
        score += 1

    # More engagement = more visible post (but lower if too many comments = already getting help)
    if 1 <= lead['num_comments'] <= 5:
        score += 1
    elif lead['num_comments'] > 10:
        score -= 1  # Probably already found someone

    return min(max(score, 1), 10)

# ==================== MAIN EXECUTION ====================

def main():
    print("="*70)
    print("🎓 REDDIT MATH TUTORING LEAD GENERATOR")
    print("="*70)
    print()

    # Validate credentials
    if not all([REDDIT_CONFIG['client_id'], REDDIT_CONFIG['client_secret'], GEMINI_API_KEY]):
        print("❌ ERROR: Missing API credentials!")
        print("→ Copy .env.template to .env and fill in your credentials")
        return

    # Step 1: Find leads
    finder = RedditLeadFinder()
    leads = finder.search_posts(hours_back=24)

    if not leads:
        print("❌ No new leads found. Try:")
        print("   - Adjusting keywords or subreddits")
        print("   - Running during peak hours (evenings/weekends)")
        print("   - Increasing hours_back parameter")
        return

    # Step 2: Score and sort leads
    for lead in leads:
        lead['priority_score'] = score_lead(lead)

    leads.sort(key=lambda x: x['priority_score'], reverse=True)

    # Step 3: Generate personalized messages for top leads
    print("🤖 Generating personalized messages with Gemini...\n")
    generator = GeminiMessageGenerator(GEMINI_API_KEY)

    num_to_process = min(len(leads), 15)  # Process top 15 leads

    for i, lead in enumerate(leads[:num_to_process]):
        print(f"\n{'='*70}")
        print(f"LEAD #{i+1} | Priority Score: {lead['priority_score']}/10")
        print(f"{'='*70}")
        print(f"📍 r/{lead['subreddit']}")
        print(f"📝 {lead['title']}")
        print(f"🔗 {lead['url']}")
        print(f"👤 u/{lead['author']}")
        print(f"⏰ Posted: {lead['created_utc']}")
        print(f"🎯 Grade: {lead['grade_level']} | Topics: {lead['topics']}")
        print(f"🚨 Urgent: {'Yes' if lead['is_urgent'] else 'No'}")
        print(f"💰 Mentions Payment: {'Yes' if lead['mentions_payment'] else 'No'}")
        print()

        message = generator.generate_personalized_message(lead)
        lead['generated_message'] = message

        print("💬 GENERATED MESSAGE:")
        print("-" * 70)
        print(message)
        print("-" * 70)

        time.sleep(3)  # Rate limit Gemini API

    # Step 4: Export to CSV
    df = pd.DataFrame(leads)
    timestamp = datetime.now().strftime('%Y%m%d_%H%M')
    output_file = f"reddit_leads_{timestamp}.csv"
    df.to_csv(output_file, index=False)

    # Update processed IDs file
    all_processed = pd.DataFrame({'post_id': list(finder.processed_ids)})
    all_processed.to_csv('processed_leads.csv', index=False)

    print(f"\n✅ Lead data exported to: {output_file}")
    print(f"✅ Processed IDs saved to: processed_leads.csv")
    print(f"\n{'='*70}")
    print("📋 SUMMARY")
    print(f"{'='*70}")
    print(f"Total leads found: {len(leads)}")
    print(f"Messages generated: {num_to_process}")
    print(f"Average priority score: {sum(l['priority_score'] for l in leads)/len(leads):.1f}/10")
    print(f"High priority (8-10): {sum(1 for l in leads if l['priority_score'] >= 8)}")
    print(f"Urgent posts: {sum(1 for l in leads if l['is_urgent'])}")
    print(f"Parent posts: {sum(1 for l in leads if l['is_parent'])}")

    print(f"\n{'='*70}")
    print("⚠️  IMPORTANT: MANUAL POSTING REQUIRED")
    print(f"{'='*70}")
    print("✓ Review each message in the CSV")
    print("✓ Make small edits for authenticity")
    print("✓ Post 5-8 messages per day MAX")
    print("✓ Wait 15-30 minutes between posts")
    print("✓ Track responses in 'status' column")
    print(f"\n📈 Recommended: Focus on priority score 7+ first")

if __name__ == "__main__":
    main()
