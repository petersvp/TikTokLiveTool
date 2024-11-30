# TikTokLiveTool

**PeterSvP's TikTokLiveTool** is a powerful gui tool that processes and categorizes TikTok LIVE stream data in realtime and can output actions to flat files. It's primary use is for providing TikTok LIVE integration for video game mods (by modders), but the tool is as general purpose as possible and can be hooked in any scenario that requires real-time reactions to LIVE feeds.

This program connects to [TikTok LIVE](https://tiktok.com/live) and receive realtime events such as comments, gifts and likes through a websocket connection to TikTok's internal Webcast service. No credentials are required to use TikTokLiveTool, you can connect to TikTok with just a *username* (`@unique_id`)

The program processes the LIVE Stream data against a flexible config file and outputs actions that react to different conditions, e.g. an action can be triggered when someone follows the streamer, specific message is typed in the chat, specific number of likes happen or someone sends specific gitfs.

## Features

- **Flexible Action Mapping**: Dynamically map TikTok events like gifts, likes, and chat messages to customizable actions outputted to a special actions file.

- **Split LIVE data to multiple output files**: Likes, gifts, chat and follows can go each into separate files, in custom defined format via the config file.

- **Likes leaderboards**: The tool can generate almost-real-time top X likes leaderboard. 

### Supported Events

- **Chat Messages**: Map specific chat messages to actions using *regex patterns.*
- **Follows and Shares**: Trigger actions when viewers *follow* or *share* the LIVE stream.
- **Gifts**: Map LIVE gifts to actions based on gift type, or on diamond thresholds.
- **Likes**: Configure actions based on the number of likes received in a batch.

## Configuration

The tool uses relaxed YAML-like configuration file to determine how events should be processed and what actions should be triggered. Below is an example configuration with fuull explanations

### Output Setup

*TikTokLiveTool* can output the unfiltered data into separate files by event type. Each event type has its own output format. Comment the `output-*` lines to disable that output type. 

*TikTokLiveTool* will quickly open, **append to** and close the *output files* to avoid file locking. Your consumer application should open, read and clear or delete the files when their data is consumed. *TikTokLiveTool* keeps and will retry the data again if a file I/O fails.

Output formats support variables. `$ts` is a timestamp, `$id` is a user id, `$user` is the user *display* name.

```yaml
output-chat: ~/TT-chat.txt
chat-format: "[$ts; $id] $user: $message"
```
`$message` is the chat message text.

```yaml
output-follow: ~/TT-follows.txt
follow-format: "[$ts; $id] $user ($count)"
```
`$count` is the *streamer's* follow count after this follow event

```yaml
output-share: ~/TT-shares.txt
share-format: "[$ts; $id] $user"
```

```yaml
output-gift: ~/TT-gifts.txt
gift-format: "[$ts; $id] $user: $gift x $quantity = $gems"
```
`$gift` is the name of the gift being sent, `$quantity` is how many times a streakable gift was sent, `$gems` is the gift gems amount received by the streamer.

**Likes** are more complex. TikTok's internal WebCast service batches likes by chunks of 15 and sends them, which makes their accumulation non-deterministic. *TikTokLiveTool* collects and sums all like packets it receives and once `likes-update-time` seconds pass, the tool will check if one of the like thresholds has been met to trigger the appropriate event. *TikTokLiveTool* will then **rewrite** the `output-likes` file with the sorted leaderboard data for all users.
```yaml
output-likes: ~/TT-likes.txt
likes-format: "[$id] $user = $count"
likes-update-time: 5
likes-mode: leaderboard # or all
likes-count: 10
```
You can make the program clear all output files when it starts. Comment the line to disable this behavior.
```yaml
outputs-reset: true
```

### Actions setup


TiktokLiveTool's main feature is filtering LIVE events based on advanced criteria
and outputting the filtered data to a special action file. This is intended to communicate with apps that need to consume specific actions. 
Check PeterSvP's Spelunky 2 TikTok Integration mod for a real world example!

```yaml
# The file where the translated & filtered output will go:
output-actions: ~/TT-actions.txt
```
Action definitions are either a single string, or an array contain one or more strings. In case array is used, one of its items will be randomly selected to be logged.

**Follows** and **Shares** are just a single action set. In this example, when someone follows the streamer, one of the array elements will be randomly logged, and when someone shares the stream, the `crate 1` action will be logged alone.
```yaml
follow: [snake 1, bat 1, lizard 1, spider 1, shopkeeper 1]
share: crate 1
```
You can disable these actions by removing them from your config.

**Chat Messages** are filtered based on regexes. For now only simple  chat mappings are supported, no regex placeholders and command arguments. The *snake*, *bat*, *lizard* and *hi* substrings can appear anywhere in the message, so the word *acrobat* will trigger *bat* as written below. You can use `^` and `$` to mark beginning / end of the strings.
```yaml
chat:
    snake: snake 1
    bat: bat 1
    lizard: lizard 1
    hi: [snake 1, bat 1, lizard 1]
    ^Hello.*friend$: hiredhand 1
    ^/shop: shopkeeper 1
    ^/gold: gold 10
    ^/crate: crate 1
```

**Mapping gifts to actions**. Gifts are the primary way to monetize your TikTok LIVE stream and some people do explusively this. You can map the gifts in two ways. Either specific gift type like `rose` or `rosa` (Yes, both exists), or by the gift's **gem price**.

```yaml 
gifts:

    # Actions mapped to specific gifts
    rose: ["snake $gems*2/3", "bat $gems*2/3", "skeleton $gems*2/3"]
    rosa: quillback 1
    finger heart: lizard 2
    TikTok: [crate 1, gems 5]
    money gun: plasmacannon 1

    # Entries starting with * are diamond amount thresholds
    *1: [snake $gems, bat $gems]
    *5: bat $gems/2
    *10: bomb $gems/3
    *99: explosion 1
```
In your gifts action definitions you can use variables and simple expressions like `"gold $gems*2/3"`. The `$gems` variable is the gem price of the gift and when implementing your gem thresholds you may want to take this variable to parametrize your action strings.

You can check the *gifts.txt* file for the price and names of currently available TikTok LIVE gifts. This file will be regenerated every time you connect to a LIVE stream.

**Likes** are received in chunks of 15 and the app is trying to batch them as closely as it can but thresholds aren't guaranteed to be time-precise and match what happened on TikTok. If a viewer sends 10 likes, waits a bit and sends another 10 likes, *TikTokLiveTool* may instead register and trigger single 20 lieks threshold instead of 2 times the 10 likes threshold. You can change the batch time using the `likes-update-time` config property. 

Here's how to define your Like thresholds. Just like gifts, you can use expressions around the `$likes` variable.
```yaml
likes:
    10: gold $likes/5
    20: gem 1
    50: crate 1
    100: [bomb $likes/5, shopkeeper 1]
```

## How to Build and Run TikTokLiveTool

### Prerequisites

Before building and running *TikTokLiveTool*, ensure you have the following installed:

1. **Python 3.8+**: Download and install Python from the [official website](https://www.python.org/downloads/).
2. **pip**: This is usually included with Python. If not, you can install it by following the [official instructions](https://pip.pypa.io/en/stable/installation/).

### Install Dependencies

Install the required Python packages using `pip`. Open your terminal or command prompt, navigate to the directory containing your project, and run:

```bash
pip install -r requirements.txt
```

If you don't have a `requirements.txt` file, you can manually install the dependencies with the following commands:

```bash
pip install customtkinter
pip install TikTokLive
pip install pyyaml
```

### Running the Tool
To run the tool directly from the source code, execute the following command in your terminal. On windows you may be able to just double-click the *pyw* file.

```bash
python TikTokLiveTool.pyw
```

### Building the project as an Executable
To distribute `TikTokLiveTool` as an executable, you can use `PyInstaller`. Follow these steps to build a executable:

#### Install PyInstaller:

If you haven't installed it yet, do so with:

```bash
pip install pyinstaller
```
#### Build the Executable:
Use the following command to build the executable. 

```bash
pyinstaller --onefile --windowed --icon=icon.ico --add-data=icon.ico:. TikTokLiveTool.pyw
```

After the build process completes, you will find `TikTokLiveTool.exe` in the dist directory inside your project folder.

### That's all of it!

If you like this tool and want to support my work, go check out my [Steam Store Page](https://store.steampowered.com/pub/pidev) and [my game, ColorBlend FX: Desaturation](https://store.steampowered.com/app/670510/ColorBlend_FX_Desaturation/). You can also check my social media.

*The TikTokLiveTool project is community maintained and not associated with ByteDance in any way.*

