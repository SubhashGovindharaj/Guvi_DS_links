from flask import Flask, render_template, request, jsonify, redirect, url_for, send_from_directory
import json
import os
import psycopg
from psycopg import pool
from psycopg.rows import dict_row
from datetime import datetime, timedelta
import requests
import re
from urllib.parse import urlparse
from dotenv import load_dotenv
import google.generativeai as genai
import logging
from contextlib import contextmanager

# Configure logging
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

load_dotenv()  # loads variables from .env

# Environment variables
GEMINI_API_KEY = os.getenv("GEMINI_API_KEY")
DATABASE_URL = os.getenv("DATABASE_URL")

# For Render, the DATABASE_URL is automatically provided
# Internal: postgresql://guvi_ds_db_user:b8EehLOj2MYVDWFa7KysAPYGEClEYYxG@dpg-d2illpbuibrs739vjdpg-a/guvi_ds_db
# External: postgresql://guvi_ds_db_user:b8EehLOj2MYVDWFa7KysAPYGEClEYYxG@dpg-d2illpbuibrs739vjdpg-a.oregon-postgres.render.com/guvi_ds_db

# If DATABASE_URL is not set, fall back to local development
if not DATABASE_URL:
    DB_HOST = os.getenv("DB_HOST", "localhost")
    DB_PORT = os.getenv("DB_PORT", "5432")
    DB_NAME = os.getenv("DB_NAME", "guvi_links")
    DB_USER = os.getenv("DB_USER", "postgres")
    DB_PASSWORD = os.getenv("DB_PASSWORD", "subhash")
    DATABASE_URL = f"postgresql://{DB_USER}:{DB_PASSWORD}@{DB_HOST}:{DB_PORT}/{DB_NAME}"

# Configure Gemini AI
if GEMINI_API_KEY:
    genai.configure(api_key=GEMINI_API_KEY)
    logger.info("✅ Gemini API configured successfully")
else:
    logger.warning("⚠️ GEMINI_API_KEY not found. Using fallback AI responses.")

app = Flask(__name__)

# PostgreSQL Database Configuration
class PostgreSQLDB:
    def __init__(self, database_url=DATABASE_URL):
        self.database_url = database_url
        self.connection_pool = None
        self.init_connection_pool()
        self.init_database()
    
    def init_connection_pool(self):
        """Initialize PostgreSQL connection pool using psycopg"""
        try:
            self.connection_pool = psycopg.pool.ConnectionPool(
                self.database_url,
                min_size=1,
                max_size=20,
                kwargs={"row_factory": dict_row}
            )
            logger.info("✅ PostgreSQL connection pool initialized")
        except Exception as e:
            logger.error(f"❌ Failed to initialize connection pool: {e}")
            raise
    
    @contextmanager
    def get_connection(self):
        """Context manager for database connections"""
        conn = None
        try:
            conn = self.connection_pool.getconn()
            yield conn
        except Exception as e:
            if conn:
                conn.rollback()
            logger.error(f"Database error: {e}")
            raise
        finally:
            if conn:
                self.connection_pool.putconn(conn)
    
    def init_database(self):
        """Initialize the database with required tables"""
        try:
            with self.get_connection() as conn:
                cursor = conn.cursor()
                
                # Create links table
                cursor.execute('''
                    CREATE TABLE IF NOT EXISTS links (
                        id SERIAL PRIMARY KEY,
                        title VARCHAR(255) NOT NULL,
                        url TEXT NOT NULL,
                        description TEXT,
                        category VARCHAR(100) NOT NULL DEFAULT 'general',
                        added_by VARCHAR(100) DEFAULT 'Anonymous',
                        clicks INTEGER DEFAULT 0,
                        created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                        updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                        last_clicked TIMESTAMP
                    )
                ''')
                
                # Create categories table
                cursor.execute('''
                    CREATE TABLE IF NOT EXISTS categories (
                        id VARCHAR(100) PRIMARY KEY,
                        name VARCHAR(255) NOT NULL,
                        color VARCHAR(50) DEFAULT 'blue',
                        created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
                    )
                ''')
                
                # Create activity_log table
                cursor.execute('''
                    CREATE TABLE IF NOT EXISTS activity_log (
                        id SERIAL PRIMARY KEY,
                        action VARCHAR(100) NOT NULL,
                        user_name VARCHAR(100),
                        link_title VARCHAR(255),
                        link_id INTEGER,
                        category VARCHAR(100),
                        timestamp TIMESTAMP DEFAULT CURRENT_TIMESTAMP
                    )
                ''')
                
                # Create indexes for better performance
                cursor.execute('''
                    CREATE INDEX IF NOT EXISTS idx_links_category ON links(category);
                ''')
                cursor.execute('''
                    CREATE INDEX IF NOT EXISTS idx_links_created_at ON links(created_at);
                ''')
                cursor.execute('''
                    CREATE INDEX IF NOT EXISTS idx_links_clicks ON links(clicks);
                ''')
                cursor.execute('''
                    CREATE INDEX IF NOT EXISTS idx_activity_timestamp ON activity_log(timestamp);
                ''')
                
                conn.commit()
                logger.info("✅ PostgreSQL database initialized successfully")
                self.create_default_categories()
                
        except Exception as e:
            logger.error(f"❌ Failed to initialize database: {e}")
            raise
    
    def create_default_categories(self):
        """Create default categories"""
        default_categories = [
            ('machine-learning', 'Machine Learning', 'blue'),
            ('data-science', 'Data Science', 'green'),
            ('deep-learning', 'Deep Learning', 'purple'),
            ('tools', 'Tools', 'orange'),
            ('documentation', 'Documentation', 'gray'),
            ('datasets', 'Datasets', 'red')
        ]
        
        try:
            with self.get_connection() as conn:
                cursor = conn.cursor()
                for cat_id, name, color in default_categories:
                    cursor.execute('''
                        INSERT INTO categories (id, name, color) 
                        VALUES (%s, %s, %s)
                        ON CONFLICT (id) DO NOTHING
                    ''', (cat_id, name, color))
                conn.commit()
                logger.info("✅ Default categories created")
        except Exception as e:
            logger.error(f"❌ Failed to create default categories: {e}")

# Initialize database
try:
    db = PostgreSQLDB()
except Exception as e:
    logger.error(f"❌ Failed to initialize database: {e}")
    raise

# CRUD Operations for Links

def create_link(link_data):
    """Create a new link in PostgreSQL"""
    try:
        with db.get_connection() as conn:
            cursor = conn.cursor()
            
            cursor.execute('''
                INSERT INTO links (title, url, description, category, added_by, clicks, created_at, updated_at)
                VALUES (%s, %s, %s, %s, %s, 0, CURRENT_TIMESTAMP, CURRENT_TIMESTAMP)
                RETURNING *
            ''', (
                link_data['title'],
                link_data['url'],
                link_data.get('description', ''),
                link_data['category'],
                link_data.get('added_by', 'Anonymous')
            ))
            
            link = cursor.fetchone()
            conn.commit()
            
            # Add to activity log
            add_activity_log({
                'action': 'added_link',
                'user_name': link_data.get('added_by', 'Anonymous'),
                'link_title': link_data['title'],
                'category': link_data['category'],
                'link_id': link['id']
            })
            
            return link
            
    except Exception as e:
        logger.error(f"❌ Failed to create link: {e}")
        raise

def read_links(category=None, search_query=None, limit=None):
    """Read links from PostgreSQL with optional filtering"""
    try:
        with db.get_connection() as conn:
            cursor = conn.cursor()
            
            query = "SELECT * FROM links WHERE 1=1"
            params = []
            
            # Add category filter
            if category and category != 'all':
                query += " AND category = %s"
                params.append(category)
            
            # Add search filter
            if search_query:
                query += " AND (title ILIKE %s OR description ILIKE %s OR category ILIKE %s OR added_by ILIKE %s)"
                search_param = f"%{search_query}%"
                params.extend([search_param, search_param, search_param, search_param])
            
            query += " ORDER BY created_at DESC"
            
            if limit:
                query += " LIMIT %s"
                params.append(limit)
            
            cursor.execute(query, params)
            links = cursor.fetchall()
            
            return links
            
    except Exception as e:
        logger.error(f"❌ Failed to read links: {e}")
        return []

def update_link(link_id, update_data):
    """Update a link in PostgreSQL"""
    try:
        with db.get_connection() as conn:
            cursor = conn.cursor()
            
            # Build update query dynamically
            set_clauses = []
            params = []
            
            for key, value in update_data.items():
                if key != 'id':  # Don't update the ID
                    set_clauses.append(f"{key} = %s")
                    params.append(value)
            
            set_clauses.append("updated_at = CURRENT_TIMESTAMP")
            params.append(link_id)
            
            query = f"UPDATE links SET {', '.join(set_clauses)} WHERE id = %s"
            
            cursor.execute(query, params)
            rows_affected = cursor.rowcount
            conn.commit()
            
            if rows_affected == 0:
                raise Exception("Link not found")
            
            # Add to activity log
            add_activity_log({
                'action': 'updated_link',
                'user_name': update_data.get('updated_by', 'Anonymous'),
                'link_id': link_id
            })
            
            return rows_affected > 0
            
    except Exception as e:
        logger.error(f"❌ Failed to update link: {e}")
        raise

def delete_link(link_id):
    """Delete a link from PostgreSQL"""
    try:
        with db.get_connection() as conn:
            cursor = conn.cursor()
            
            # Get link info before deletion
            cursor.execute("SELECT * FROM links WHERE id = %s", (link_id,))
            link = cursor.fetchone()
            
            if not link:
                raise Exception("Link not found")
            
            cursor.execute("DELETE FROM links WHERE id = %s", (link_id,))
            rows_affected = cursor.rowcount
            conn.commit()
            
            if rows_affected > 0:
                # Add to activity log
                add_activity_log({
                    'action': 'deleted_link',
                    'user_name': 'System',
                    'link_title': link['title'],
                    'link_id': link_id
                })
            
            return rows_affected > 0
            
    except Exception as e:
        logger.error(f"❌ Failed to delete link: {e}")
        raise

def increment_link_clicks(link_id):
    """Increment click count for a link"""
    try:
        with db.get_connection() as conn:
            cursor = conn.cursor()
            
            cursor.execute('''
                UPDATE links 
                SET clicks = clicks + 1, last_clicked = CURRENT_TIMESTAMP 
                WHERE id = %s
            ''', (link_id,))
            
            rows_affected = cursor.rowcount
            conn.commit()
            
            return rows_affected > 0
            
    except Exception as e:
        logger.error(f"❌ Failed to increment clicks: {e}")
        return False

# CRUD Operations for Categories

def create_category(category_data):
    """Create a new category"""
    try:
        category_id = category_data['name'].lower().replace(' ', '-')
        
        with db.get_connection() as conn:
            cursor = conn.cursor()
            
            cursor.execute('''
                INSERT INTO categories (id, name, color) 
                VALUES (%s, %s, %s)
                ON CONFLICT (id) DO NOTHING
                RETURNING *
            ''', (category_id, category_data['name'], category_data.get('color', 'blue')))
            
            result = cursor.fetchone()
            if not result:
                raise Exception("Category already exists")
                
            conn.commit()
            
            return result
            
    except Exception as e:
        logger.error(f"❌ Failed to create category: {e}")
        raise

def read_categories():
    """Read all categories"""
    try:
        with db.get_connection() as conn:
            cursor = conn.cursor()
            cursor.execute("SELECT * FROM categories")
            
            categories = {}
            for row in cursor.fetchall():
                categories[row['id']] = {
                    'name': row['name'],
                    'color': row['color']
                }
            
            return categories
            
    except Exception as e:
        logger.error(f"❌ Failed to read categories: {e}")
        return {}

# Activity Log Functions

def add_activity_log(activity_data):
    """Add activity to log"""
    try:
        with db.get_connection() as conn:
            cursor = conn.cursor()
            
            cursor.execute('''
                INSERT INTO activity_log (action, user_name, link_title, link_id, category)
                VALUES (%s, %s, %s, %s, %s)
            ''', (
                activity_data.get('action'),
                activity_data.get('user_name'),
                activity_data.get('link_title'),
                activity_data.get('link_id'),
                activity_data.get('category')
            ))
            
            conn.commit()
            
            # Keep only last 100 activities
            cursor.execute("SELECT COUNT(*) FROM activity_log")
            count = cursor.fetchone()['count']
            
            if count > 100:
                cursor.execute('''
                    DELETE FROM activity_log 
                    WHERE id IN (
                        SELECT id FROM activity_log 
                        ORDER BY timestamp ASC 
                        LIMIT %s
                    )
                ''', (count - 100,))
                conn.commit()
            
    except Exception as e:
        logger.error(f"❌ Failed to add activity log: {e}")

def get_activity_log(limit=20):
    """Get recent activity log"""
    try:
        with db.get_connection() as conn:
            cursor = conn.cursor()
            cursor.execute('''
                SELECT * FROM activity_log 
                ORDER BY timestamp DESC 
                LIMIT %s
            ''', (limit,))
            
            activities = cursor.fetchall()
            return activities
            
    except Exception as e:
        logger.error(f"❌ Failed to get activity log: {e}")
        return []

# Statistics Functions

def get_statistics():
    """Get comprehensive statistics"""
    try:
        with db.get_connection() as conn:
            cursor = conn.cursor()
            
            # Total links
            cursor.execute("SELECT COUNT(*) as count FROM links")
            total_links = cursor.fetchone()['count']
            
            # Links this week
            cursor.execute('''
                SELECT COUNT(*) as count FROM links 
                WHERE created_at >= CURRENT_DATE - INTERVAL '7 days'
            ''')
            links_this_week = cursor.fetchone()['count']
            
            # Category distribution
            cursor.execute('''
                SELECT category, COUNT(*) as count 
                FROM links 
                GROUP BY category 
                ORDER BY count DESC
            ''')
            category_stats = cursor.fetchall()
            category_distribution = {row['category']: row['count'] for row in category_stats}
            most_used_category = category_stats[0]['category'] if category_stats else 'Data Science'
            
            # Total clicks
            cursor.execute("SELECT COALESCE(SUM(clicks), 0) as total_clicks FROM links")
            total_clicks = cursor.fetchone()['total_clicks']
            
            # Recent activity
            team_activity = get_activity_log(10)
            
            return {
                'total_links': total_links,
                'links_this_week': links_this_week,
                'most_used_category': most_used_category,
                'category_distribution': category_distribution,
                'total_clicks': total_clicks,
                'team_activity': team_activity
            }
            
    except Exception as e:
        logger.error(f"❌ Failed to get statistics: {e}")
        return {
            'total_links': 0,
            'links_this_week': 0,
            'most_used_category': 'Data Science',
            'category_distribution': {},
            'total_clicks': 0,
            'team_activity': []
        }

# Utility Functions

def validate_url(url):
    """Simple URL validation"""
    try:
        result = urlparse(url)
        return all([result.scheme, result.netloc])
    except:
        return False

def extract_links_from_text(text):
    """Extract URLs from text"""
    url_pattern = re.compile(r'http[s]?://(?:[a-zA-Z]|[0-9]|[$-_@.&+]|[!*\\(\\),]|(?:%[0-9a-fA-F][0-9a-fA-F]))+')
    return url_pattern.findall(text)

def extract_title_from_context(text, url):
    """Extract title from text context around the URL"""
    try:
        url_pos = text.find(url)
        if url_pos == -1:
            return None
        
        before_text = text[:url_pos].strip()
        lines_before = before_text.split('\n')
        
        if lines_before:
            potential_title = lines_before[-1].strip()
            potential_title = re.sub(r'^[-•*\s]+', '', potential_title)
            potential_title = re.sub(r'[^\w\s-]', '', potential_title)
            
            if 10 <= len(potential_title) <= 100:
                return potential_title[:80]
        
        return None
    except:
        return None

# AI Response Functions

def get_ai_response(query, chat_history=None):
    """Get AI response using Gemini API with database context"""
    try:
        if GEMINI_API_KEY:
            model = genai.GenerativeModel('gemini-1.5-flash')
            
            # Get context from database
            stats = get_statistics()
            recent_links = read_links(limit=10)
            
            context_info = f"\nAvailable resources: {stats['total_links']} links across categories"
            if stats['category_distribution']:
                categories = ', '.join([f"{cat}: {count}" for cat, count in stats['category_distribution'].items()])
                context_info += f"\nCategory breakdown: {categories}"
            
            history_context = ""
            if chat_history:
                recent_history = chat_history[-3:] if len(chat_history) > 3 else chat_history
                history_context = "\nRecent conversation:\n" + "\n".join([
                    f"{'User' if msg['role'] == 'user' else 'Assistant'}: {msg['content']}" 
                    for msg in recent_history
                ])
            
            prompt = f"""You are GUVI's helpful AI assistant for a data science team's link hub. You help team members find and discover resources about data science, machine learning, deep learning, datasets, tools, and documentation.

Query: {query}
{context_info}
{history_context}

Guidelines:
- Be conversational, helpful, and enthusiastic about data science
- Provide specific, actionable advice
- If asking about resources, mention what types might be available
- Keep responses concise but informative (2-3 sentences max)
- Use emojis occasionally to be friendly
- If the query is about adding resources or technical issues, provide helpful guidance

Respond as the GUVI AI assistant:"""
            
            response = model.generate_content(prompt)
            return response.text
            
    except Exception as e:
        logger.error(f"Gemini API error: {e}")
    
    return get_smart_fallback_response(query)

def get_smart_fallback_response(query):
    """Smart fallback AI responses"""
    query_lower = query.lower()
    stats = get_statistics()
    
    # Greeting responses
    greetings = ['hello', 'hi', 'hey', 'good morning', 'good afternoon', 'good evening']
    if any(greeting in query_lower for greeting in greetings):
        if stats['total_links'] > 0:
            return f"🌟 Hello! I'm your GUVI AI assistant. I can help you explore our {stats['total_links']} resources across {len(stats['category_distribution'])} categories. What are you looking for today?"
        else:
            return "🌟 Hello! I'm your GUVI AI assistant. Ready to help you find data science resources. What would you like to learn about?"
    
    # Machine Learning queries
    ml_keywords = ['machine learning', 'ml', 'algorithm', 'model', 'supervised', 'unsupervised', 'classification', 'regression']
    if any(keyword in query_lower for keyword in ml_keywords):
        ml_count = stats['category_distribution'].get('machine-learning', 0)
        if ml_count > 0:
            return f"🤖 Great! I found {ml_count} machine learning resources in our collection. I can help you discover algorithms, frameworks like scikit-learn, TensorFlow basics, and practical ML tutorials."
        else:
            return "🤖 Machine learning is fascinating! I can help you find resources about algorithms, model training, scikit-learn, and practical ML implementations. Try adding some ML resources to build our collection!"
    
    # Default response with context
    if stats['total_links'] > 0:
        top_categories = list(stats['category_distribution'].keys())[:3]
        category_list = ", ".join(top_categories)
        return f"🚀 I'm here to help you explore our {stats['total_links']} resources in {category_list} and more. What specific topic or type of resource are you looking for?"
    else:
        return "🚀 I'm your GUVI AI assistant! I can help you find data science resources, organize your learning materials, and guide you through ML/AI topics. Try asking me about machine learning, datasets, or tools you'd like to explore!"

# Flask Routes

@app.route('/')
def index():
    """Main page - render template with initial data"""
    try:
        # Get initial data for the template
        categories = read_categories()
        links = read_links(limit=20)  # Load first 20 links
        stats = get_statistics()
        
        return render_template('index.html', 
                             categories=categories,
                             links=links,
                             stats=stats)
    except Exception as e:
        logger.error(f"❌ Error loading main page: {e}")
        # Fallback to basic template without data
        return render_template('index.html', 
                             categories={},
                             links=[],
                             stats={})

@app.route('/add_link', methods=['POST'])
def add_link():
    """Add a new link"""
    try:
        url = request.form['url']
        if not validate_url(url):
            return jsonify({'error': 'Invalid URL format'}), 400
        
        link_data = {
            'title': request.form['title'].strip(),
            'url': url,
            'description': request.form.get('description', '').strip(),
            'category': request.form['category'],
            'added_by': request.form.get('added_by', 'Anonymous').strip() or 'Anonymous'
        }
        
        created_link = create_link(link_data)
        logger.info(f"✅ Added new resource: {created_link['title']} by {created_link['added_by']}")
        
        return jsonify({'success': True, 'link': created_link})
        
    except Exception as e:
        logger.error(f"❌ Failed to add link: {e}")
        return jsonify({'error': str(e)}), 400

@app.route('/delete_link/<int:link_id>', methods=['DELETE'])
def delete_link_route(link_id):
    """Delete a link"""
    try:
        success = delete_link(link_id)
        if success:
            logger.info(f"🗑️ Deleted resource with ID: {link_id}")
            return jsonify({'success': True})
        else:
            return jsonify({'error': 'Link not found'}), 404
            
    except Exception as e:
        logger.error(f"❌ Failed to delete link: {e}")
        return jsonify({'error': str(e)}), 400

@app.route('/click_link/<int:link_id>', methods=['POST'])
def click_link(link_id):
    """Track link clicks"""
    try:
        success = increment_link_clicks(link_id)
        if success:
            logger.info(f"👆 Click tracked for link ID: {link_id}")
        return jsonify({'success': success})
        
    except Exception as e:
        logger.error(f"❌ Failed to track click: {e}")
        return jsonify({'success': False})

@app.route('/search')
def search():
    """Search links"""
    query = request.args.get('q', '').strip()
    category = request.args.get('category', None)
    
    if not query and not category:
        links = read_links(limit=50)
    else:
        links = read_links(category=category, search_query=query)
    
    logger.info(f"🔍 Search for '{query}' in category '{category}' returned {len(links)} results")
    return jsonify(links)

@app.route('/ai_chat', methods=['POST'])
def ai_chat():
    """Enhanced AI chatbot endpoint"""
    user_message = request.json.get('message', '').strip()
    chat_history = request.json.get('history', [])
    
    if not user_message:
        return jsonify({
            'response': "I'm here to help! What would you like to know about data science resources?",
            'relevant_links': []
        })
    
    logger.info(f"💬 AI Chat - User: {user_message}")
    
    try:
        ai_response = get_ai_response(user_message, chat_history)
        logger.info(f"🤖 AI Response generated")
    except Exception as e:
        logger.error(f"⚠️ AI Error: {e}")
        ai_response = get_smart_fallback_response(user_message)
    
    # Find relevant links using database search
    relevant_links = read_links(search_query=user_message, limit=5)
    
    logger.info(f"🎯 Found {len(relevant_links)} relevant resources")
    
    return jsonify({
        'response': ai_response,
        'relevant_links': relevant_links
    })

@app.route('/import_from_text', methods=['POST'])
def import_from_text():
    """Import links from text with PostgreSQL storage"""
    try:
        text_content = request.json.get('content', '').strip()
        category = request.json.get('category', 'imported')
        added_by = request.json.get('added_by', 'Anonymous').strip() or 'Anonymous'
        
        if not text_content:
            return jsonify({'error': 'No content provided'}), 400
        
        urls = extract_links_from_text(text_content)
        
        if not urls:
            return jsonify({'error': 'No valid URLs found in the text'}), 400
        
        imported_links = []
        skipped_count = 0
        
        for url in urls:
            if validate_url(url):
                try:
                    title = extract_title_from_context(text_content, url) or f"Imported Resource"
                    
                    link_data = {
                        'title': title,
                        'url': url,
                        'description': f'Imported from text on {datetime.now().strftime("%Y-%m-%d")}',
                        'category': category,
                        'added_by': added_by
                    }
                    
                    created_link = create_link(link_data)
                    imported_links.append(created_link)
                    
                except Exception as e:
                    logger.warning(f"⚠️ Skipped URL {url}: {e}")
                    skipped_count += 1
            else:
                skipped_count += 1
        
        result_message = f"Successfully imported {len(imported_links)} resources"
        if skipped_count > 0:
            result_message += f" ({skipped_count} duplicates/invalid URLs skipped)"
        
        logger.info(f"📥 Import complete: {len(imported_links)} new resources by {added_by}")
        
        return jsonify({
            'success': True,
            'imported_count': len(imported_links),
            'skipped_count': skipped_count,
            'message': result_message,
            'links': imported_links
        })
        
    except Exception as e:
        logger.error(f"❌ Import failed: {e}")
        return jsonify({'error': str(e)}), 400

@app.route('/stats')
def get_stats_route():
    """Get comprehensive team statistics"""
    try:
        stats = get_statistics()
        
        # Get top links by clicks
        top_links = read_links(limit=10)
        top_links.sort(key=lambda x: x.get('clicks', 0), reverse=True)
        stats['top_links'] = top_links[:5]
        
        return jsonify(stats)
        
    except Exception as e:
        logger.error(f"❌ Failed to get stats: {e}")
        return jsonify({'error': str(e)}), 400

@app.route('/categories')
def get_categories_route():
    """Get all categories"""
    try:
        categories = read_categories()
        return jsonify(categories)
        
    except Exception as e:
        logger.error(f"❌ Failed to get categories: {e}")
        return jsonify({})

@app.route('/add_category', methods=['POST'])
def add_category():
    """Add a new category"""
    try:
        category_data = {
            'name': request.json.get('name', '').strip(),
            'color': request.json.get('color', 'blue')
        }
        
        if not category_data['name']:
            return jsonify({'error': 'Category name is required'}), 400
        
        created_category = create_category(category_data)
        logger.info(f"➕ Added new category: {created_category['name']}")
        
        return jsonify({
            'success': True,
            'category': created_category
        })
        
    except Exception as e:
        logger.error(f"❌ Failed to add category: {e}")
        return jsonify({'error': str(e)}), 400

@app.route('/export')
def export_data():
    """Export all data as JSON"""
    try:
        links = read_links()
        categories = read_categories()
        stats = get_statistics()
        
        export_data = {
            'export_date': datetime.utcnow().isoformat(),
            'total_links': len(links),
            'categories': categories,
            'links': links,
            'stats': stats
        }
        
        return jsonify(export_data)
        
    except Exception as e:
        logger.error(f"❌ Export failed: {e}")
        return jsonify({'error': str(e)}), 400

@app.route('/health')
def health_check():
    """Health check endpoint"""
    return jsonify({
        'status': 'healthy',
        'timestamp': datetime.utcnow().isoformat(),
        'database_url': DATABASE_URL.replace(DATABASE_URL.split('@')[0].split('://')[-1], '***') if DATABASE_URL else 'Not configured',
        'gemini_configured': bool(GEMINI_API_KEY)
    })

# Template filters
@app.template_filter('datetime')
def datetime_filter(value):
    """Format datetime for display"""
    try:
        if isinstance(value, str):
            dt = datetime.fromisoformat(value.replace('Z', ''))
        else:
            dt = value
        return dt.strftime('%Y-%m-%d %H:%M')
    except:
        return value

@app.template_filter('timeago')
def timeago_filter(value):
    """Human readable time ago"""
    try:
        if isinstance(value, str):
            dt = datetime.fromisoformat(value.replace('Z', ''))
        else:
            dt = value
        
        now = datetime.utcnow()
        diff = now - dt
        
        if diff.days > 0:
            return f"{diff.days} day{'s' if diff.days != 1 else ''} ago"
        elif diff.seconds > 3600:
            hours = diff.seconds // 3600
            return f"{hours} hour{'s' if hours != 1 else ''} ago"
        elif diff.seconds > 60:
            minutes = diff.seconds // 60
            return f"{minutes} minute{'s' if minutes != 1 else ''} ago"
        else:
            return "just now"
    except:
        return value

# Error handlers
@app.errorhandler(404)
def not_found_error(error):
    return jsonify({'error': 'Resource not found'}), 404

@app.errorhandler(500)
def internal_error(error):
    logger.error(f"Internal server error: {error}")
    return jsonify({'error': 'Internal server error'}), 500

@app.errorhandler(400)
def bad_request(error):
    return jsonify({'error': 'Bad request'}), 400

if __name__ == '__main__':
    logger.info("🚀 Starting GUVI Link Hub with PostgreSQL on Render...")
    logger.info(f"📊 Database: PostgreSQL (psycopg)")
    logger.info(f"🤖 Gemini AI: {'✅ Enabled' if GEMINI_API_KEY else '⚠️ Using fallback responses'}")
    
    # Check if templates directory exists
    current_dir = os.path.dirname(os.path.abspath(__file__))
    templates_dir = os.path.join(current_dir, 'templates')
    index_html_path = os.path.join(templates_dir, 'index.html')
    
    if os.path.exists(index_html_path):
        logger.info("✅ templates/index.html found")
    else:
        logger.warning(f"⚠️ templates/index.html not found at {index_html_path}")
        logger.warning("📁 Make sure index.html is in the templates/ directory")
    
    # Check static directory
    static_dir = os.path.join(current_dir, 'static')
    if os.path.exists(static_dir):
        logger.info("✅ static/ directory found")
        static_files = os.listdir(static_dir)
        logger.info(f"📁 Static files: {', '.join(static_files)}")
    else:
        logger.warning("⚠️ static/ directory not found")
    
    port = int(os.environ.get('PORT', 5000))
    app.run(debug=False, host='0.0.0.0', port=port)
