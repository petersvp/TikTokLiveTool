import webbrowser, threading, queue, time, yaml, re, os, random, sys, math
import customtkinter as ctk
from collections import defaultdict
from TikTokLive import TikTokLiveClient
from TikTokLive.events import (
    ConnectEvent, DisconnectEvent, CommentEvent,
    LikeEvent, FollowEvent, ShareEvent, GiftEvent,
    EmoteChatEvent, SubscribeEvent
)


# Global variables for TikTok client and Tkinter
client = None
log_area = None
message_queue = queue.Queue()  # A thread-safe queue for log messages

pending_chats = []
pending_follows = []
pending_shares = []
pending_gifts = []
pending_actions = []

def preprocess_yaml_string(yaml_str):
    def quote_key(match):
        indent = match.group(1)  # Leading spaces
        key = match.group(2)     # The actual key
        return f'{indent}"{key}":'
    
    # Only process lines that are not comments
    def process_line(line):
        if line.strip().startswith('#'):
            return line
        return re.sub(r'^(\s*)([^:\s][^:\n]*):', quote_key, line)

    # Apply processing to each line individually
    yaml_lines = yaml_str.splitlines()
    processed_lines = [process_line(line) for line in yaml_lines]
    return '\n'.join(processed_lines)

def open_link(url):
    webbrowser.open(url)

# Event handler functions
def on_connect(event: ConnectEvent):
    message_queue.put((f"Connected to @{event.unique_id} (Room ID: {client.room_id})\n", None))
    
    try:
        with open("gifts.txt", 'wb') as f:
            for g in sorted(client.gift_info["gifts"], key=lambda item: item['diamond_count']):
                f.write((f"{g['name']}: {g['diamond_count']}\n").encode("utf-8"))
    except Exception as e:
        print(f"Error logging action: {e}")

def on_disconnect(event: DisconnectEvent):
    message_queue.put(("Disconnected from the LIVE.\n", None))

def on_comment(event: CommentEvent):
    message = event.comment
    log_chat(event.user, message)
    for pattern, action in chats:
        if re.match(pattern.lower(), message.lower()):
            message_queue.put((event.user.nickname, f": {message}"))
            action = get_action(action)
            #log_action(get_action(action))
            break

def on_follow(event: FollowEvent):
    log_follow(event.user, event.follow_count)
    follow_action = get_action(config['follow'])
    if follow_action:
        message_queue.put((event.user.nickname, " followed the host"))
        log_action(follow_action)

def on_share(event: ShareEvent):
    log_share(event.user)
    share_action = get_action(config.get('share', None))
    if share_action:
        message_queue.put((event.user.nickname, " shared the stream"))
        log_action(share_action)

def on_gift(event: GiftEvent):
    gift_name = event.gift.name.lower()
    gift_diamonds = event.gift.diamond_count * event.repeat_count
       
    if (not event.gift.streakable) or (event.gift.streakable and not event.streaking):
        
        log_gift(event.user, gift_name, gift_diamonds, event.repeat_count)

        # Resolve which action to trigger
        action = None
        for key, action_template in gifts:
            if not key.startswith('*') and key.lower() == gift_name:
                action = action_template
        if not action:
            for key, action_template in gifts:
                if key.startswith('*') and gift_diamonds >= int(key[1:]):
                    action = action_template
        # trigger the action
        if action:
            action = resolve_var(get_action(action), 'gems', gift_diamonds)
            if event.gift.streakable:
                message_queue.put((event.user.nickname, f" sent {gift_name} x{event.repeat_count} = {gift_diamonds}💎"))
                for _ in range(event.repeat_count):
                    log_action(action)
            else:
                message_queue.put((event.user.nickname, f" sent {gift_name} = {gift_diamonds}💎"))
                log_action(action)

def on_subscribe(event: SubscribeEvent):
    user_name = event.user.nickname
    for pattern, action in subscriptions:
        if re.match(pattern, user_name):
            message_queue.put((user_name, " subscribed to the host"))
            log_action(action)
            break

def on_emote(event: EmoteChatEvent):
    message_queue.put((event.user.nickname, f" sent an emote: {event.emote.id}"))

# Like processing - TikTok sends likes by batches of 15 likes
likes_mutex = threading.RLock()
user_likes = defaultdict(lambda: (0, 0.0, None))
user_likes_ldb = defaultdict(lambda: (0, None))
def on_like(event: LikeEvent):
    if likes.count == 0: return
    like_count = event.count
    with likes_mutex: # writing on Client thread
        user_likes[event.user.id] = (user_likes[event.user.id][0]+like_count, time.time() + 5, event.user);
        if 'output-likes' in config:
            user_likes_ldb[event.user.id] = (user_likes_ldb[event.user.id][0]+like_count, event.user)

next_ldb_time = 0.0
def process_likes():
    t = time.time()
    with likes_mutex: # iterating on GUI thread
        # Process user_likes and trigger LIKE actions
        for userid, data in user_likes.items():
            if t >= data[1]:
                like_action = None
                for threshold, action in likes:
                    if data[0] >= int(threshold):
                        like_action = resolve_var(get_action(action), 'likes', data[0])
                        break
                if like_action:
                    message_queue.put((data[2].nickname, f" sent {data[0]} likes"))
                    log_action(like_action)
                del user_likes[userid]
                break 
        
        # Process user_likes_ldb
        if 'output-likes' in config:
            global next_ldb_time
            if time.time() > next_ldb_time:
                # Sort user_likes_ldb by like count (0th element in the tuple) in descending order
                sorted_likes = sorted(user_likes_ldb.items(), key=lambda item: item[1][0], reverse=True)

                # If likes-mode is 'leaderboard', limit the entries to 'likes-count'
                if config['likes-mode'] == 'leaderboard':
                    sorted_likes = sorted_likes[:config['likes-count']]

                # Prepare the formatted messages
                formatted_messages = []
                for user_id, (count, user) in sorted_likes:
                    formatted_message = config['likes-format'].replace('$id', user.display_id).replace('$user', user.nickname).replace('$count', str(count))
                    formatted_messages.append(formatted_message)

                # Write the results to the output file
                try:
                    with open(os.path.expanduser(config['output-likes']), 'wb') as likes_file:
                        for message in formatted_messages:
                            likes_file.write( (message + '\n').encode('utf-8'))
                            next_ldb_time = time.time() + config.get('likes-update-time', 10);
                except Exception as e:
                    print(f"Error writing likes leaderboard: {e}")

# Function to start the TikTok client
def start_client(username): 
    global client
    while True:
        try:
            client = TikTokLiveClient(unique_id=username)
            
            # Add event listeners
            client.add_listener(ConnectEvent, on_connect)
            client.add_listener(DisconnectEvent, on_disconnect)
            client.add_listener(CommentEvent, on_comment)
            client.add_listener(LikeEvent, on_like)
            client.add_listener(FollowEvent, on_follow)
            client.add_listener(ShareEvent, on_share)
            client.add_listener(GiftEvent, on_gift)
            client.add_listener(SubscribeEvent, on_subscribe)
            client.add_listener(EmoteChatEvent, on_emote)
            
            # Start the client (blocking call)
            client.run(fetch_gift_info=True)
        
        except Exception as e:
            # Log the exception (or handle it as needed)
            message_queue.put(("ERROR", f": {str(e)}"))
            
            # Wait a bit before trying to reconnect
            time.sleep(5)
            message_queue.put((" =>", " Attempting to reconnect to LIVE..."))

# Function to handle log window close event
def on_log_window_close(log_window, root):
    root.destroy()  # Destroy the root window, which will quit the app

# Function to handle connect button click
def on_connect_click(username_entry, root):
    username = username_entry.get()
    if username:
        root.withdraw()  # Hide the main window

        # Create a new window for logging
        log_window = ctk.CTkToplevel(root)
        log_window.title(f"{username}'s TikTok Live Log")
        log_window.geometry("500x400")

        # Bind the close event of the log window to ensure proper shutdown
        log_window.protocol("WM_DELETE_WINDOW", lambda: on_log_window_close(log_window, root))

        # Create a resizable text area for logging
        global log_area
        log_area = ctk.CTkTextbox(log_window, width=480, height=380, state='disabled')
        log_area.pack(padx=10, pady=10, expand=True, fill='both')  # Make it fill the window and resizable

        # Access the underlying Text widget and define a bold tag for usernames
        text_widget = log_area._textbox  # Access the underlying Text widget
        text_widget.tag_configure('bold', font=('Segoe UI', 10, 'bold'))

        # Run TikTok client in the background thread
        client_thread = threading.Thread(target=start_client, args=(username,), daemon=True)
        client_thread.start()

        # Start checking the message queue
        log_window.after(100, process_events)

# Function to handle cancel button click
def on_cancel_click(root):
    root.destroy()

def resource(relative_path):
    base_path = getattr(
        sys,
        '_MEIPASS',
        os.path.dirname(os.path.abspath(__file__)))
    return os.path.join(base_path, relative_path)

# Function to create the Main window
def create_main_window():
    # Set appearance mode and color theme for dark background
    ctk.set_appearance_mode("Dark")  # Use "Dark" mode for a dark theme
    ctk.set_default_color_theme("green")  # You can choose from "blue", "dark-blue", "green"

    # Create the main window
    root = ctk.CTk()
    root.title("PeterSvP's Tool for TikTok LIVE")
    root.geometry("400x250")
    root.wm_iconbitmap(resource('icon.ico'))

    # Create a main frame to hold all widgets with a dark background
    main_frame = ctk.CTkFrame(root)
    main_frame.pack(padx=4, pady=4, expand=True, fill='both')

    # Create a label for the username input
    username_label = ctk.CTkLabel(main_frame, text="Enter the @username of the LIVE creator", font=('Segoe UI', 16))
    username_label.pack(pady=16)

    # Create a text entry field for the username
    username_entry = ctk.CTkEntry(main_frame, width=300, font=('Segoe UI', 16))
    username_entry.pack(pady=10)

    # Create a frame for the buttons with a specified height
    button_frame = ctk.CTkFrame(main_frame, height=80)  # Increase the height as needed
    button_frame.pack(pady=10, padx=10)

    # Adjust button padding within the frame to center them vertically
    cancel_button = ctk.CTkButton(button_frame, text="Cancel", command=lambda: on_cancel_click(root),
                                fg_color='#555', text_color='white', corner_radius=10, width=120)
    cancel_button.pack(side=ctk.LEFT, padx=10, pady=10)  # Add some vertical padding

    connect_button = ctk.CTkButton(button_frame, text="Connect", command=lambda: on_connect_click(username_entry, root),
                                fg_color='#11a61f', text_color='white', corner_radius=20, width=120)
    connect_button.pack(side=ctk.LEFT, padx=10, pady=10)  # Add some vertical padding

    # Create an undecorated frame for the clickable text at the bottom
    bottom_frame = ctk.CTkFrame(main_frame, fg_color="transparent")
    bottom_frame.pack(side='bottom', pady=10)

    # First line of clickable text
    label1_frame = ctk.CTkFrame(bottom_frame, fg_color="transparent")
    label1_frame.pack()

    label1_texts = [
        ("Made by PeterSvP", None),
        (" • TikTok", "https://www.tiktok.com/@petersvp"),
        (" • Instagram", "https://www.instagram.com/petersvp"),
        (" • Steam", "https://store.steampowered.com/pub/pidev"),
        (" • PayPal", "https://paypal.me/petersvp"),
    ]
    first = True
    for text, url in label1_texts:
        if url:
            link_label = ctk.CTkLabel(label1_frame, text=text, font=('Segoe UI', 12, 'bold' if first else 'normal'), 
                                      text_color="#FFFFFF" if first else '#cccccc', height=6, cursor="hand2")
            link_label.bind("<Button-1>", lambda e, url=url: open_link(url))
        else:
            link_label = ctk.CTkLabel(label1_frame, text=text, font=('Segoe UI', 12), text_color="#FFFFFF", height=6)
        link_label.pack(side="left", pady=0)
        first = False

    # Second line of clickable text
    label2 = ctk.CTkLabel(bottom_frame, text="Check my 2.5D puzzle game, Desaturation on STEAM", font=('Segoe UI', 11), height=18, text_color="#ccccff", cursor="hand2")
    label2.bind("<Button-1>", lambda e: open_link("https://store.steampowered.com/app/670510/ColorBlend_FX_Desaturation"))
    label2.pack(pady=0)

    return root

# Function to check the message queue and update the log area
def process_events():
    process_likes()
    while not message_queue.empty():
        title, comment = message_queue.get()
        log_area.configure(state='normal')  # Enable editing to add text

        if comment is None:
            # For system messages like connection confirmation
            log_area.insert(ctk.END, title)
        else:
            # Insert the username with a bold tag
            log_area.insert(ctk.END, title, 'bold')
            # Insert the comment normally
            log_area.insert(ctk.END, f"{comment}\n")
        
        log_area.configure(state='disabled')  # Make it read-only again
        log_area.see(ctk.END)  # Scroll to the end

    # Schedule the function to be called again after 100ms
    log_area.after(16, process_events)

def log_chat(user, message):
    if 'output-chat' in config:
        ts = time.strftime("%Y-%m-%d %H:%M:%S", time.localtime())
        formatted_message = config['chat-format'].replace('$ts', ts).replace('$id', user.display_id).replace('$user', user.nickname).replace('$message', message)
        log_entry(formatted_message, pending_chats, os.path.expanduser(config['output-chat']))

def log_follow(user, follow_count):
    if 'output-follow' in config:
        ts = time.strftime("%Y-%m-%d %H:%M:%S", time.localtime())
        formatted_message = config['follow-format'].replace('$ts', ts).replace('$id', user.display_id).replace('$user', user.nickname).replace('$count', str(follow_count))
        log_entry(formatted_message, pending_follows, os.path.expanduser(config['output-follow']))

def log_share(user):
    if 'output-share' in config:
        ts = time.strftime("%Y-%m-%d %H:%M:%S", time.localtime())
        formatted_message = config['share-format'].replace('$ts', ts).replace('$id', user.display_id).replace('$user', user.nickname)
        log_entry(formatted_message, pending_shares, os.path.expanduser(config['output-share']))

def log_gift(user, gift_name, diamond_count, quantity):
    if 'output-gift' in config:
        ts = time.strftime("%Y-%m-%d %H:%M:%S", time.localtime())
        formatted_message = (config['gift-format']
                             .replace('$ts', ts)
                             .replace('$id', user.display_id)
                             .replace('$user', user.nickname)
                             .replace('$gift', gift_name)
                             .replace('$gems', str(diamond_count))
                             .replace('$quantity', str(quantity)))
        log_entry(formatted_message, pending_gifts, os.path.expanduser(config['output-gift']))

def log_action(action):
    global pending_actions
    log_entry(action, pending_actions, os.path.expanduser(config['output-actions']))

def log_entry(entry, entry_queue, file_name):
    entry_queue.append(entry)
    try:
        with open(file_name, 'ab') as output_file:
            for i in entry_queue:
                output_file.write((i + '\n').encode("utf-8"))
        entry_queue.clear()
    except Exception as e:
        print(f"Error logging action: {e}")

# Get random value from config
def get_action(x):
    if isinstance(x, list):
        return random.choice(x)
    return x

# used for expression evaluation
def resolve_var(action, var_name, var_value):
    safe_env = { var_name: var_value }
    def safe_eval(match):
        expression = match.group(0)[1:]  # Remove the leading '$'
        try:
            return str(math.ceil(eval(expression, {"__builtins__": {}}, safe_env)))
        except Exception:
            return match.group(0)  # Return the original string if eval fails

    resolved_action = re.sub(rf'\${var_name}(?:[*/+-]\d+(?:\.\d+)?)*', safe_eval, action)    
    return resolved_action

# Load config
def load_config():
    global config, chats, gifts, subscriptions, likes
    config = {'output': '~/output.log'}
    try:
        with open("config.cfg", 'r') as file:
            configfile = preprocess_yaml_string(file.read())
            print(configfile)
            config.update(yaml.safe_load(configfile))
    except Exception as e:
        print(f"Error loading config: {e}")
    
    # Load and sort chats
    chat_dict = config.get('chat', {})
    chats = sorted(chat_dict.items(), key=lambda item: -len(item[0]))  # Sort by length of pattern (descending)

    # Load and sort gifts
    gift_dict = config.get('gifts', {})
    gifts = sorted(
        gift_dict.items(), 
        key=lambda item: (int(item[0][1:]) if item[0].startswith('*') else float('inf'), item[0])
    )

    # Likes 
    like_dict = config.get('likes', {});
    likes = sorted(
        like_dict.items(), 
        key=lambda item: int(item[0]), reverse=True
    )

    # Load and sort subscriptions if applicable
    subscriptions_dict = config.get('subscriptions', {})
    subscriptions = sorted(subscriptions_dict.items())  # Assuming alphabetical sort is suitable

def init_files():
    # Check if 'outputs-reset' is set to true in the config
    if config.get('outputs-reset', False):
        # List of output file keys to reset
        output_files = [
            'output-chat', 
            'output-follow', 
            'output-share', 
            'output-gift', 
            'output-likes',
            'output-actions'
        ]
        
        # Iterate over each output file key in the config
        for file_key in output_files:
            if file_key in config:
                try:
                    # Reset the file by opening it in write mode (w) to clear the contents
                    with open(os.path.expanduser(config[file_key]), 'w') as file:
                        pass  # Just open and close to reset
                    print(f"Reset file: {config[file_key]}")
                except Exception as e:
                    print(f"Error resetting file {config[file_key]}: {e}")

# Load config, make ui
if __name__ == '__main__':
    load_config()
    init_files()
    print(config)
    root = create_main_window()
    root.mainloop()
