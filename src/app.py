import pandas as pd
from flask import Flask, request, render_template
from pymongo import MongoClient
from collections import Counter
from wordcloud import WordCloud
import matplotlib.pyplot as plt
import matplotlib
matplotlib.use('Agg')
import io
import base64

# ---> Initialize Flask app
app = Flask(__name__)

# ---> Connect to MongoDB
client = MongoClient("mongodb://localhost:27017/")
db = client["Brand_Analysis"]
collection = db["Articles"]

# ---> Neo4j connection setup
neo4j_driver = GraphDatabase.driver("bolt://localhost:7689", auth=("neo4j", "apan5400"))


# ---> Define common adjectives to exclude from analysis
GENERIC_ADJECTIVES = {
    "new", "old", "high", "young", "big", "good", "bad", "great", "free", 
    "little", "more", "less", "second", "best", "first", "last", "next", "nike",
    "adidas", "asics", "hoka", "lululemon", "new balance", "puma", "reebok", "under armour"
}

# ---> Predefined list of logos available for front-end display
available_logos = ["adidas", "asics", "hoka", "lululemon", "new balance", "nike", "puma", "reebok", "under armour"]

# ---> Get all unique brand names from the mongodb database
all_brands = sorted(set(
    brand.lower()
    for doc in collection.find({"brands_mentioned": {"$exists": True}})
    for brand in doc.get("brands_mentioned", [])
    if isinstance(brand, str)
))

# ---> Function to retrieve top adjectives for a given brand
def get_top_adjectives_for_brand(brand_name, top_n=10):
    brand_name = brand_name.lower()
    adjective_counter = Counter()
    
    # Find documents where the brand is mentioned and adjectives are present
    cursor = collection.find({
        "brands_mentioned": {"$in": [brand_name]},
        "adjectives": {"$exists": True}
    }, {"adjectives": 1})

    # Filter out generic adjectives and count occurrences
    for doc in cursor:
        filtered = [adj for adj in doc["adjectives"] if adj.lower() not in GENERIC_ADJECTIVES]
        adjective_counter.update(filtered)

    # Return top N most common adjectives
    return adjective_counter.most_common(top_n), [adj for adj, _ in adjective_counter.most_common(top_n)]

# ---> Function to generate word cloud 
def generate_wordcloud(adjectives):
    wordcloud = WordCloud(width=800, height=400, background_color='white').generate(' '.join(adjectives))

    # Convert image to base64 string for HTML embedding
    img_buffer = io.BytesIO()
    wordcloud.to_image().save(img_buffer, format="PNG")
    img_buffer.seek(0)
    img_base64 = base64.b64encode(img_buffer.getvalue()).decode('utf-8')
    return img_base64

# ---> Function to get number of brand mentions by year 
def get_brand_mentions_by_year(brand_name):
    brand_name = brand_name.lower()
    pipeline = [
        {"$match": {"brands_mentioned": brand_name, "year": {"$exists": True}}},
        {"$group": {"_id": "$year", "count": {"$sum": 1}}},
        {"$sort": {"_id": 1}}
    ]

    # MongoDB aggregation to group mention counts by year
    results = list(collection.aggregate(pipeline))
    years = [res["_id"] for res in results]

    # Extract years and counts into lists
    counts = [res["count"] for res in results]
    return years, counts

# ---> Function to generate bar chart for top adjectives
def generate_adjective_bar_chart(brand_name):
    top_adjectives, _ = get_top_adjectives_for_brand(brand_name, top_n=10)
    
    # If there are less than 10 adjectives, pad with empty ones
    if len(top_adjectives) < 10:
        top_adjectives.extend([('', 0)] * (10 - len(top_adjectives)))
    
    # Create a DataFrame
    top_df = pd.DataFrame(top_adjectives, columns=["Adjective", "Frequency"])
    
    # Sort the DataFrame for better visualization
    top_df = top_df.sort_values(by="Frequency", ascending=True)

    # Plot horizontal bar chart
    fig, ax = plt.subplots(figsize=(10, 6))
    ax.barh(top_df["Adjective"], top_df["Frequency"], color='skyblue')
    ax.set_xlabel("Frequency")
    ax.set_title(f"Top 10 Adjectives for {brand_name.capitalize()}")

    # Save the plot to a BytesIO object
    img_buffer = io.BytesIO()
    plt.tight_layout()
    plt.savefig(img_buffer, format='png')
    img_buffer.seek(0)
    img_base64 = base64.b64encode(img_buffer.getvalue()).decode('utf-8')
    
    # Close the plot to free memory
    plt.close(fig)
    
    return img_base64


# ---> Add this new function to app.py (place it with the other functions)
def get_brands_by_adjective(adjective_name):
    adjective_name = adjective_name.lower()
    brand_counter = Counter()
    
    # Find documents where the adjective is present and brands are mentioned
    cursor = collection.find({
        "adjectives": {"$in": [adjective_name]},
        "brands_mentioned": {"$exists": True}
    }, {"brands_mentioned": 1})

    # Count brand occurrences
    for doc in cursor:
        brands = [brand.lower() for brand in doc.get("brands_mentioned", [])]
        brand_counter.update(brands)

    # Return all brands with their counts
    return brand_counter.most_common()
    

# ---> Define main route for GET & POST
@app.route('/', methods=['GET', 'POST'])
def index():
    
    # Initialize default variables for template
    brand_query = ''
    brand_results = []
    adjective_query = ''
    adjective_results = []
    wordcloud_image = None
    mentions_years = []
    mentions_counts = []
    image_url = 'static/images/Neo4j_graph.png' 
    bar_chart_image = None 
    brands_by_adjective = []
    

    # POST requests
    if request.method == 'POST':
        if 'brand' in request.form:
            brand_query = request.form['brand'].strip().lower()
            brand_results, top_adjs = get_top_adjectives_for_brand(brand_query)
            wordcloud_image = generate_wordcloud(top_adjs)
            mentions_years, mentions_counts = get_brand_mentions_by_year(brand_query)
            bar_chart_image = generate_adjective_bar_chart(brand_query) 

        # If user searched by adjective
        if 'adjective' in request.form:
            adjective_query = request.form['adjective'].strip().lower()
            if adjective_query:
                cursor = collection.find({
                    "adjectives": {"$in": [adjective_query]},
                }).limit(25)                                                 # Fetch only 25 matching articles
                adjective_results = [doc.get("title") for doc in cursor]

        # Add this new block to handle adjective search for brands
        if 'adjective_brand_search' in request.form:
            adjective_query = request.form['adjective_brand_search'].strip().lower()
            if adjective_query:
                brands_by_adjective = get_brands_by_adjective(adjective_query)

    
    # Always display default word cloud for Nike on page load
    top_adjectives, top_adjs = get_top_adjectives_for_brand("nike")
    nike_wordcloud = generate_wordcloud(top_adjs)

    # Always display default word cloud for Nike on page load
    top_adjectives, top_adjs = get_top_adjectives_for_brand("nike")
    nike_wordcloud = generate_wordcloud(top_adjs)

    # Render index.html 
    return render_template('index.html',
                           brand=brand_query,
                           brand_results=brand_results,
                           adjective=adjective_query,
                           adjective_results=adjective_results,
                           all_brands=all_brands,
                           top_adjectives=top_adjectives,
                           available_logos=available_logos,
                           wordcloud_image=wordcloud_image or nike_wordcloud,
                           mentions_years=mentions_years,
                           mentions_counts=mentions_counts,
                          image_url=image_url,
                          brands_by_adjective=brands_by_adjective,
                          bar_chart_image=bar_chart_image)

# ---> Run Flask app locally on mentioned port
if __name__ == '__main__':
    app.run(debug=True, port=5056, use_reloader=False)
