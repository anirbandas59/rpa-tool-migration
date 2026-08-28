#!/usr/bin/env python3
"""
Build the PAD action index: extract PDF descriptions + confirmed syntax from real PAD source files.

This script:
1. Extracts actions from the PDF cheat sheet (friendly name, category, description)
2. Scans all real PAD source files (.robin/.txt) for actual action-call syntax
3. Aligns PDF entries to real syntax via category + keyword heuristics
4. Emits docs/pad-reference/pad-action-index.yaml with:
   - dotted_name (if confirmed in real source)
   - friendly_name (from PDF)
   - category (from PDF)
   - description (from PDF)
   - confidence: "confirmed" | "description-only"
   - syntax: actual call (if confirmed)
   - syntax_source: file + line (if confirmed)

Purpose: curation-time search index keyed by PAD action intent/description; complements
vbo_catalogue.yaml (runtime lookup keyed by BP VBO).
"""

import re
from dataclasses import asdict, dataclass
from difflib import SequenceMatcher
from pathlib import Path

import yaml


@dataclass
class ActionEntry:
    """A single PAD action entry for the index."""

    friendly_name: str
    category: str
    description: str
    confidence: str  # "confirmed" | "description-only"
    dotted_name: str | None = None
    syntax: str | None = None
    syntax_source: str | None = None  # "file:line"
    alignment: str | None = None  # "confirmed" | "unconfirmed"


# Complete PDF actions extracted from the Power Automate Desktop Actions Cheat Sheet (19 pages)
# Extracted from pdftotext -layout output covering all ~40+ categories in the PDF
# Prior version extracted only ~14 categories (90 actions); this version comprehensively
# covers the entire PDF: Variables, UI automation (4 subcats), Browser automation (3 subcats),
# Excel (+ Advanced), Office 365 Outlook, SharePoint, Word, Word Online, OneDrive,
# OneDrive for Business, Outlook, Exchange Server, Office 365 Teams, Microsoft Forms,
# Microsoft Dataverse, Work queues, HTTP, Mouse and keyboard, Azure (3 subcats),
# AWS (3 subcats), Active Directory (3 subcats), Cryptography, CyberArk, Google cognitive
# (2 subcats), IBM cognitive (4 subcats), Microsoft cognitive (3 subcats), SAP automation,
# Terminal emulation, FTP, File, Folder, Compression, Text, Date time, Scripting, System,
# PDF, XML, Database, CMD session, Windows services, OCR, Workstation, Conditionals, Loops,
# Flow control, Clipboard, AI Builder, Power Automate secret variables, Variables - Data table,
# Logging, RSS, and more.
PDF_ACTIONS = [
    # Variables
    {
        "category": "Variables",
        "friendly_name": "Truncate number",
        "description": "Get the integral or fractional digits of a numeric value, or round up to specified decimal places",
    },
    {
        "category": "Variables",
        "friendly_name": "Generate random number",
        "description": "Generate a random number or a list of random numbers that fall between a minimum and maximum value",
    },
    {
        "category": "Variables",
        "friendly_name": "Clear list",
        "description": "Remove all items from a list",
    },
    {
        "category": "Variables",
        "friendly_name": "Remove item from list",
        "description": "Remove one or multiple items from a list",
    },
    {
        "category": "Variables",
        "friendly_name": "Sort list",
        "description": "Sort the items of a list. Use items of the same type",
    },
    {
        "category": "Variables",
        "friendly_name": "Shuffle list",
        "description": "Create a random permutation of a list",
    },
    {
        "category": "Variables",
        "friendly_name": "Merge lists",
        "description": "Merge two lists into one",
    },
    {
        "category": "Variables",
        "friendly_name": "Reverse list",
        "description": "Reverse the order of the items of a list",
    },
    {
        "category": "Variables",
        "friendly_name": "Remove duplicate items from list",
        "description": "Remove the multiple occurrences of items in a list",
    },
    {
        "category": "Variables",
        "friendly_name": "Find common list items",
        "description": "Compare two lists and create a new list with the items that are common to both",
    },
    {
        "category": "Variables",
        "friendly_name": "Subtract lists",
        "description": "Compare two lists and create a new list with the items that are in the first but not in the second",
    },
    {
        "category": "Variables",
        "friendly_name": "Retrieve data table column into list",
        "description": "Convert the contents of a data table column into a list",
    },
    {
        "category": "Variables",
        "friendly_name": "Convert JSON to custom object",
        "description": "Convert a JSON string to a custom object",
    },
    {
        "category": "Variables",
        "friendly_name": "Convert custom object to JSON",
        "description": "Convert a custom object to a JSON string",
    },
    {
        "category": "Variables",
        "friendly_name": "Add item to list",
        "description": "Append a new item to a list",
    },
    {
        "category": "Variables",
        "friendly_name": "Create new list",
        "description": "Create a new empty list",
    },
    {
        "category": "Variables",
        "friendly_name": "Increase variable",
        "description": "Increase the value of a variable by a specific amount",
    },
    {
        "category": "Variables",
        "friendly_name": "Decrease variable",
        "description": "Decrease the value of a variable by a specific amount",
    },
    {
        "category": "Variables",
        "friendly_name": "Set variable",
        "description": "Set the value of a new or existing variable",
    },
    # UI automation
    {
        "category": "UI automation",
        "friendly_name": "If window contains",
        "description": "Mark the beginning of a conditional block of actions depending on whether a specific piece of text or UI element exists in a window",
    },
    {
        "category": "UI automation",
        "friendly_name": "Wait for window content",
        "description": "Suspends the execution of the automation until a specific piece of text or UI element appears or disappears from a window",
    },
    {
        "category": "UI automation",
        "friendly_name": "If image",
        "description": "Mark the beginning of a conditional block depending on whether a selected image is found on the screen or not",
    },
    {
        "category": "UI automation",
        "friendly_name": "Wait for image",
        "description": "This action waits until a specific image appears on the screen",
    },
    {
        "category": "UI automation",
        "friendly_name": "Hover mouse over UI element in window",
        "description": "Hover the mouse over any UI element on window",
    },
    {
        "category": "UI automation",
        "friendly_name": "Click UI element in window",
        "description": "Clicks on any UI element of a window",
    },
    {
        "category": "UI automation",
        "friendly_name": "Select menu option in window",
        "description": "Selects an option in a menu of a window",
    },
    {
        "category": "UI automation",
        "friendly_name": "Drag and drop UI element in window",
        "description": "Drags and drops a UI element of a window",
    },
    {
        "category": "UI automation",
        "friendly_name": "Expand/collapse tree node in window",
        "description": "Expands or collapses a node of a tree view residing in a window",
    },
    {
        "category": "UI automation",
        "friendly_name": "If window",
        "description": "Mark the beginning of a conditional block depending on whether a window is open or focused",
    },
    {
        "category": "UI automation",
        "friendly_name": "Wait for window",
        "description": "Suspends execution until a specific window opens, closes, or changes focus",
    },
    {
        "category": "UI automation",
        "friendly_name": "Use desktop",
        "description": "Performs desktop and taskbar related operations",
    },
    {
        "category": "UI automation",
        "friendly_name": "Select tab in window",
        "description": "Selects a tab from a group of tabs",
    },
    # UI automation - Data Extraction
    {
        "category": "UI automation - Data Extraction",
        "friendly_name": "Get details of window",
        "description": "Gets a property of a window such as its title or its source text",
    },
    {
        "category": "UI automation - Data Extraction",
        "friendly_name": "Get details of a UI element in window",
        "description": "Gets the value of a UI element's attribute in a window",
    },
    {
        "category": "UI automation - Data Extraction",
        "friendly_name": "Get selected checkboxes in window",
        "description": "Retrieves the names of the selected checkboxes in a checkbox group",
    },
    {
        "category": "UI automation - Data Extraction",
        "friendly_name": "Get selected radio button in window",
        "description": "Retrieves the names of the selected radio button in a radio button group",
    },
    {
        "category": "UI automation - Data Extraction",
        "friendly_name": "Extract data from window",
        "description": "Extracts data from specific parts of a window in the form of single values, lists, or tables",
    },
    {
        "category": "UI automation - Data Extraction",
        "friendly_name": "Take screenshot of UI element",
        "description": "Takes a screenshot of a UI element in window",
    },
    {
        "category": "UI automation - Data Extraction",
        "friendly_name": "Extract data from table",
        "description": "Extracts data from a table in the form of a datatable",
    },
    # UI automation - Form filling
    {
        "category": "UI automation - Form filling",
        "friendly_name": "Focus text field in window",
        "description": "Sets the focus on a text box of a window",
    },
    {
        "category": "UI automation - Form filling",
        "friendly_name": "Populate text field in window",
        "description": "Fills a text box in a window with the specified text",
    },
    {
        "category": "UI automation - Form filling",
        "friendly_name": "Press button in window",
        "description": "Presses a window button",
    },
    {
        "category": "UI automation - Form filling",
        "friendly_name": "Select radio button in window",
        "description": "Selects a radio button on a window",
    },
    {
        "category": "UI automation - Form filling",
        "friendly_name": "Set checkbox state in window",
        "description": "Checks or unchecks a checkbox in a window form",
    },
    {
        "category": "UI automation - Form filling",
        "friendly_name": "Set drop-down list value in window",
        "description": "Sets or clears the selected option(s) for a drop-down list in a window form",
    },
    # UI automation - Windows
    {
        "category": "UI automation - Windows",
        "friendly_name": "Get window",
        "description": "Gets a running window, for automating desktop applications",
    },
    {
        "category": "UI automation - Windows",
        "friendly_name": "Focus window",
        "description": "Activates and brings to the foreground a specific window",
    },
    {
        "category": "UI automation - Windows",
        "friendly_name": "Set window state",
        "description": "Restores, maximizes or minimizes a specific window",
    },
    {
        "category": "UI automation - Windows",
        "friendly_name": "Set window visibility",
        "description": "Shows a hidden window or hides a visible window",
    },
    {
        "category": "UI automation - Windows",
        "friendly_name": "Move window",
        "description": "Sets the position of a specific window",
    },
    {
        "category": "UI automation - Windows",
        "friendly_name": "Resize window",
        "description": "Sets the size of a specific window",
    },
    {
        "category": "UI automation - Windows",
        "friendly_name": "Close window",
        "description": "Closes a specific window",
    },
    # Browser automation
    {
        "category": "Browser automation",
        "friendly_name": "If web page contains",
        "description": "Mark the beginning of a conditional block of actions depending on whether a specific piece of text or element exists in a web page",
    },
    {
        "category": "Browser automation",
        "friendly_name": "Wait for web page content",
        "description": "Suspend the flow until a specific piece of text or web page element appears or disappears from a web page",
    },
    {
        "category": "Browser automation",
        "friendly_name": "Launch new Internet Explorer",
        "description": "Launch a new instance or attach to a running instance of Internet Explorer",
    },
    {
        "category": "Browser automation",
        "friendly_name": "Launch new Firefox",
        "description": "Launch a new instance or attach to a running instance of Firefox",
    },
    {
        "category": "Browser automation",
        "friendly_name": "Launch new Chrome",
        "description": "Launch a new instance or attach to a running instance of Chrome",
    },
    {
        "category": "Browser automation",
        "friendly_name": "Launch new Edge",
        "description": "Launch a new instance or attach to a running instance of Edge",
    },
    {
        "category": "Browser automation",
        "friendly_name": "Create new tab",
        "description": "Create a new tab and navigate to the given URL",
    },
    {
        "category": "Browser automation",
        "friendly_name": "Go to web page",
        "description": "Navigate the web browser to a new page",
    },
    {
        "category": "Browser automation",
        "friendly_name": "Click link on web page",
        "description": "Click on a link or any other element of a web page",
    },
    {
        "category": "Browser automation",
        "friendly_name": "Click download link on web page",
        "description": "Click on a link in a web page that results in downloading a file",
    },
    {
        "category": "Browser automation",
        "friendly_name": "Run JavaScript function on web page",
        "description": "Run a JavaScript function on the web page and get the returned result",
    },
    {
        "category": "Browser automation",
        "friendly_name": "Hover mouse over element on web page",
        "description": "Hover the mouse over an element of a web page",
    },
    {
        "category": "Browser automation",
        "friendly_name": "Close web browser",
        "description": "Close a web browser window",
    },
    # Browser automation - Web data extraction
    {
        "category": "Browser automation - Web data extraction",
        "friendly_name": "Extract data from web page",
        "description": "Extract data from specific parts of a web page in the form of single values, lists, rows or tables",
    },
    {
        "category": "Browser automation - Web data extraction",
        "friendly_name": "Get details of web page",
        "description": "Get a property of a web page, such as its title or its source text",
    },
    {
        "category": "Browser automation - Web data extraction",
        "friendly_name": "Get details of element on web page",
        "description": "Get the value of an element's attribute on a web page",
    },
    {
        "category": "Browser automation - Web data extraction",
        "friendly_name": "Take screenshot of web page",
        "description": "Take a screenshot of the web page currently displayed in the browser",
    },
    # Browser automation - Web form filling
    {
        "category": "Browser automation - Web form filling",
        "friendly_name": "Focus text field on web page",
        "description": "Set the focus on an input element of a web page",
    },
    {
        "category": "Browser automation - Web form filling",
        "friendly_name": "Populate text field on web page",
        "description": "Fill a text field in a web page with the specified text",
    },
    {
        "category": "Browser automation - Web form filling",
        "friendly_name": "Set check box state on web page",
        "description": "Check or uncheck a check box in a web form",
    },
    {
        "category": "Browser automation - Web form filling",
        "friendly_name": "Select radio button on web page",
        "description": "Select a radio button on the web page",
    },
    {
        "category": "Browser automation - Web form filling",
        "friendly_name": "Set drop-down list value on web page",
        "description": "Set or clear the selected option for a drop-down list in a web form",
    },
    {
        "category": "Browser automation - Web form filling",
        "friendly_name": "Press button on web page",
        "description": "Press a web page button",
    },
    # HTTP
    {
        "category": "HTTP",
        "friendly_name": "Download from web",
        "description": "Downloads text or a file from the web and stores it",
    },
    {
        "category": "HTTP",
        "friendly_name": "Invoke SOAP web service",
        "description": "Invokes a method from a SOAP web service",
    },
    {
        "category": "HTTP",
        "friendly_name": "Invoke web service",
        "description": "Invokes a web service by sending data and retrieves the response",
    },
    # Mouse and keyboard
    {
        "category": "Mouse and keyboard",
        "friendly_name": "Block Input",
        "description": "Blocks user mouse and keyboard input",
    },
    {
        "category": "Mouse and keyboard",
        "friendly_name": "Get mouse position",
        "description": "Retrieves the current position of the mouse cursor on the screen",
    },
    {
        "category": "Mouse and keyboard",
        "friendly_name": "Move mouse",
        "description": "Moves the mouse to a specific position",
    },
    {
        "category": "Mouse and keyboard",
        "friendly_name": "Move mouse to image",
        "description": "Moves the mouse over an image found on screen",
    },
    {
        "category": "Mouse and keyboard",
        "friendly_name": "Move mouse to text on screen (OCR)",
        "description": "Moves the mouse over a text found on the screen using OCR",
    },
    {
        "category": "Mouse and keyboard",
        "friendly_name": "Send mouse click",
        "description": "Sends a mouse click event",
    },
    {
        "category": "Mouse and keyboard",
        "friendly_name": "Send keys",
        "description": "Sends keys to the application that is currently active",
    },
    {
        "category": "Mouse and keyboard",
        "friendly_name": "Press/release key",
        "description": "Presses or releases one or more modifier keys",
    },
    {
        "category": "Mouse and keyboard",
        "friendly_name": "Set key state",
        "description": "Sets the state for the keys Caps Lock, Num Lock or Scroll Lock",
    },
    {
        "category": "Mouse and keyboard",
        "friendly_name": "Wait for mouse",
        "description": "Suspends the execution of the flow until the mouse pointer changes",
    },
    {
        "category": "Mouse and keyboard",
        "friendly_name": "Get keyboard identifier",
        "description": "Retrieves the active keyboard identifier from the machine's registry",
    },
    {
        "category": "Mouse and keyboard",
        "friendly_name": "Wait for shortcut key",
        "description": "Pause the flow run until a specific shortcut key is pressed",
    },
    # Azure
    {
        "category": "Azure",
        "friendly_name": "Create session",
        "description": "Creates an Azure session",
    },
    {
        "category": "Azure",
        "friendly_name": "Get subscriptions",
        "description": "Gets subscriptions that the current account can access",
    },
    {"category": "Azure", "friendly_name": "End session", "description": "Ends an Azure session"},
    # Azure - Resource groups
    {
        "category": "Azure - Resource groups",
        "friendly_name": "Get resource groups",
        "description": "Gets the resource groups based on the specified criteria",
    },
    {
        "category": "Azure - Resource groups",
        "friendly_name": "Create resource group",
        "description": "Creates a new resource group",
    },
    {
        "category": "Azure - Resource groups",
        "friendly_name": "Delete resource group",
        "description": "Deletes the specified resource group and all the contained resources",
    },
    # Azure - Virtual machines
    {
        "category": "Azure - Virtual machines",
        "friendly_name": "Get virtual machines",
        "description": "Gets the basic information for the virtual machines",
    },
    {
        "category": "Azure - Virtual machines",
        "friendly_name": "Describe virtual machine",
        "description": "Gets all the information for the virtual machine(s)",
    },
    {
        "category": "Azure - Virtual machines",
        "friendly_name": "Start virtual machine",
        "description": "Starts the virtual machine",
    },
    {
        "category": "Azure - Virtual machines",
        "friendly_name": "Stop virtual machine",
        "description": "Stops the virtual machine and deallocates the related hardware",
    },
    {
        "category": "Azure - Virtual machines",
        "friendly_name": "Shut down virtual machine",
        "description": "Shuts down the operating system of a virtual machine",
    },
    {
        "category": "Azure - Virtual machines",
        "friendly_name": "Restart virtual machine",
        "description": "Restarts a virtual machine",
    },
    # Azure - Virtual machines - Snapshots
    {
        "category": "Azure - Virtual machines - Snapshots",
        "friendly_name": "Get snapshots",
        "description": "Gets the snapshots based on the specified criteria",
    },
    {
        "category": "Azure - Virtual machines - Snapshots",
        "friendly_name": "Create snapshot",
        "description": "Creates a snapshot from the specified disk",
    },
    {
        "category": "Azure - Virtual machines - Snapshots",
        "friendly_name": "Delete snapshot",
        "description": "Deletes the snapshot with the specified name",
    },
    # Azure - Virtual machines - Disks
    {
        "category": "Azure - Virtual machines - Disks",
        "friendly_name": "Get disks",
        "description": "Gets the disks based on the specified criteria",
    },
    {
        "category": "Azure - Virtual machines - Disks",
        "friendly_name": "Attach disk",
        "description": "Attaches an existing disk to the virtual machine",
    },
    {
        "category": "Azure - Virtual machines - Disks",
        "friendly_name": "Detach disk",
        "description": "Detaches the disk from the virtual machine",
    },
    {
        "category": "Azure - Virtual machines - Disks",
        "friendly_name": "Create managed disk",
        "description": "Creates a managed disk with the specified settings",
    },
    {
        "category": "Azure - Virtual machines - Disks",
        "friendly_name": "Delete disk",
        "description": "Deletes the managed disk with the specified name",
    },
    # Cryptography
    {
        "category": "Cryptography",
        "friendly_name": "Encrypt text with AES",
        "description": "Encrypts text using AES encryption",
    },
    {
        "category": "Cryptography",
        "friendly_name": "Decrypt text with AES",
        "description": "Decrypts text using AES decryption",
    },
    {
        "category": "Cryptography",
        "friendly_name": "Encrypt from file with AES",
        "description": "Encrypts the contents of a file with AES",
    },
    {
        "category": "Cryptography",
        "friendly_name": "Decrypt to file with AES",
        "description": "Decrypts a string to a file with AES",
    },
    {
        "category": "Cryptography",
        "friendly_name": "Hash text",
        "description": "Hashs a string using a specified algorithm",
    },
    {
        "category": "Cryptography",
        "friendly_name": "Hash from file",
        "description": "Hashs the contents of a file using a specified algorithm",
    },
    {
        "category": "Cryptography",
        "friendly_name": "Hash text with key",
        "description": "Hashs a string with a key using a specified algorithm",
    },
    {
        "category": "Cryptography",
        "friendly_name": "Hash from file with key",
        "description": "Hashs the contents of a file with a key",
    },
    # CyberArk
    {
        "category": "CyberArk",
        "friendly_name": "Get password from CyberArk",
        "description": "Retrieves a password for a specific application from CyberArk",
    },
    # Google cognitive - Natural language
    {
        "category": "Google cognitive - Natural language",
        "friendly_name": "Analyze sentiment",
        "description": "Invokes the Google Cloud Natural Language service named 'Analyze Sentiment'",
    },
    {
        "category": "Google cognitive - Natural language",
        "friendly_name": "Analyze entities",
        "description": "Invokes the Google Cloud Natural Language service named 'Analyze Entities'",
    },
    {
        "category": "Google cognitive - Natural language",
        "friendly_name": "Analyze syntax",
        "description": "Invokes the Google Cloud Natural Language service named 'Analyze Syntax'",
    },
    # Google cognitive - Vision
    {
        "category": "Google cognitive - Vision",
        "friendly_name": "Label detection",
        "description": "Invokes the Google Cloud Vision service named 'Label Detection'",
    },
    {
        "category": "Google cognitive - Vision",
        "friendly_name": "Landmark detection",
        "description": "Invokes the Google Cloud Vision service named 'Landmark Detection'",
    },
    {
        "category": "Google cognitive - Vision",
        "friendly_name": "Text Detection",
        "description": "Invokes the Google Cloud Vision service named 'Text Detection'",
    },
    {
        "category": "Google cognitive - Vision",
        "friendly_name": "Logo detection",
        "description": "Invokes the Google Cloud Vision service named 'Logo Detection'",
    },
    {
        "category": "Google cognitive - Vision",
        "friendly_name": "Image properties detection",
        "description": "Invokes the Google Cloud Vision service named 'Image Properties Detection'",
    },
    {
        "category": "Google cognitive - Vision",
        "friendly_name": "Safe search detection",
        "description": "Invokes the Google Cloud Vision service named 'Safe Search Detection'",
    },
    # SharePoint (40+ actions)
    {
        "category": "SharePoint",
        "friendly_name": "Update file",
        "description": "Updates the contents of the file specified by the file identifier",
    },
    {
        "category": "SharePoint",
        "friendly_name": "Delete file",
        "description": "Deletes the file specified by the file identifier",
    },
    {
        "category": "SharePoint",
        "friendly_name": "Get file content using path",
        "description": "Gets file contents using the file path",
    },
    {
        "category": "SharePoint",
        "friendly_name": "Get file content",
        "description": "Gets file contents using the file identifier",
    },
    {
        "category": "SharePoint",
        "friendly_name": "Create file",
        "description": "Uploads a file to a SharePoint site",
    },
    {
        "category": "SharePoint",
        "friendly_name": "List folder",
        "description": "Returns files contained in a SharePoint folder",
    },
    {
        "category": "SharePoint",
        "friendly_name": "Get all lists and libraries",
        "description": "Gets all lists and libraries",
    },
    {
        "category": "SharePoint",
        "friendly_name": "Get file metadata",
        "description": "Gets information about the file such as size, etag, created date",
    },
    {
        "category": "SharePoint",
        "friendly_name": "Get file metadata using path",
        "description": "Gets information about the file using the file path",
    },
    {
        "category": "SharePoint",
        "friendly_name": "Get folder metadata",
        "description": "Gets information about the folder",
    },
    {
        "category": "SharePoint",
        "friendly_name": "Get folder metadata using path",
        "description": "Gets information about the folder using path",
    },
    {
        "category": "SharePoint",
        "friendly_name": "List root folder",
        "description": "Returns files in the root SharePoint folder",
    },
    {
        "category": "SharePoint",
        "friendly_name": "Extract folder",
        "description": "Extracts an archive file into a SharePoint folder",
    },
    {
        "category": "SharePoint",
        "friendly_name": "Get lists",
        "description": "Gets SharePoint lists from a site",
    },
    {
        "category": "SharePoint",
        "friendly_name": "Create sharing link for a file or folder",
        "description": "Creates sharing link for a file or folder",
    },
    {
        "category": "SharePoint",
        "friendly_name": "Copy file",
        "description": "Copies a file in a similar way to the Copy to command",
    },
    {
        "category": "SharePoint",
        "friendly_name": "Move file",
        "description": "Moves a file in a similar way to the Move to command",
    },
    {
        "category": "SharePoint",
        "friendly_name": "Copy folder",
        "description": "Copies a folder into a destination folder",
    },
    {
        "category": "SharePoint",
        "friendly_name": "Move folder",
        "description": "Moves an existing folder into a destination folder",
    },
    {
        "category": "SharePoint",
        "friendly_name": "Check out file",
        "description": "Check out a file in a document library to prevent others from editing",
    },
    {
        "category": "SharePoint",
        "friendly_name": "Discard check out",
        "description": "Discard the checkout of a file rather than saving it",
    },
    {
        "category": "SharePoint",
        "friendly_name": "Check in file",
        "description": "Check in a checked out file in a document library",
    },
    {
        "category": "SharePoint",
        "friendly_name": "Get list views",
        "description": "Gets views from a SharePoint list",
    },
    {
        "category": "SharePoint",
        "friendly_name": "Add attachment",
        "description": "Adds a new attachment to the specified list item",
    },
    {
        "category": "SharePoint",
        "friendly_name": "Set content approval status",
        "description": "Sets the content approval status for an item in a list or library",
    },
    {
        "category": "SharePoint",
        "friendly_name": "Stop sharing an item or a file",
        "description": "Delete all links giving access to an item or a file",
    },
    {
        "category": "SharePoint",
        "friendly_name": "Update file properties",
        "description": "Updates the properties stored in columns in a library",
    },
    {
        "category": "SharePoint",
        "friendly_name": "Update file properties using AI Builder",
        "description": "Updates the values stored in library columns for a file analyzed by a model",
    },
    {
        "category": "SharePoint",
        "friendly_name": "Get file properties",
        "description": "Gets the properties saved in the columns in the library",
    },
    {
        "category": "SharePoint",
        "friendly_name": "Get files (properties only)",
        "description": "Gets the properties saved in the columns in the library for all files",
    },
    {
        "category": "SharePoint",
        "friendly_name": "Create item",
        "description": "Creates a new item in a SharePoint list",
    },
    {
        "category": "SharePoint",
        "friendly_name": "Create new folder",
        "description": "Creates a new folder or folder path",
    },
    {
        "category": "SharePoint",
        "friendly_name": "Delete attachment",
        "description": "Deletes the specified attachment",
    },
    {
        "category": "SharePoint",
        "friendly_name": "Delete item",
        "description": "Deletes an item from a SharePoint list",
    },
    {
        "category": "SharePoint",
        "friendly_name": "Generate document using Microsoft Syntex",
        "description": "Creates documents based on modern templates from Microsoft Syntex",
    },
    {
        "category": "SharePoint",
        "friendly_name": "Get attachment content",
        "description": "Returns file contents using the file identifier",
    },
    {
        "category": "SharePoint",
        "friendly_name": "Get attachments",
        "description": "Returns the list of attachments for the specified list item",
    },
    {
        "category": "SharePoint",
        "friendly_name": "Get changes for an item or a file",
        "description": "Returns information about columns that have changed",
    },
    {
        "category": "SharePoint",
        "friendly_name": "Update item",
        "description": "Updates an item in a SharePoint list",
    },
    {
        "category": "SharePoint",
        "friendly_name": "Get item",
        "description": "Gets a single item by its id from a SharePoint list",
    },
    {
        "category": "SharePoint",
        "friendly_name": "Get items",
        "description": "Gets items from a SharePoint list",
    },
    {
        "category": "SharePoint",
        "friendly_name": "Create new document set",
        "description": "Creates a new document list item",
    },
    {
        "category": "SharePoint",
        "friendly_name": "Grant access to an item or a folder",
        "description": "Grant access to an item or a folder in SharePoint to specific people",
    },
    {
        "category": "SharePoint",
        "friendly_name": "Send an HTTP request to SharePoint",
        "description": "Construct a SharePoint REST API to invoke",
    },
    # Word
    {
        "category": "Word",
        "friendly_name": "Launch Word",
        "description": "Opens a new Word instance or opens a Word document",
    },
    {
        "category": "Word",
        "friendly_name": "Attach to running Word",
        "description": "Attaches to a Word document that's already open",
    },
    {
        "category": "Word",
        "friendly_name": "Save Word",
        "description": "Saves a previously launched Word instance",
    },
    {"category": "Word", "friendly_name": "Close Word", "description": "Closes a Word instance"},
    {
        "category": "Word",
        "friendly_name": "Read from Word document",
        "description": "Reads the text content from a document of a Word instance",
    },
    {
        "category": "Word",
        "friendly_name": "Write to Word document",
        "description": "Writes or appends text to a Word file",
    },
    {
        "category": "Word",
        "friendly_name": "Insert image in Word document",
        "description": "Inserts an image to a Word file",
    },
    {
        "category": "Word",
        "friendly_name": "Find and replace words in Word document",
        "description": "Finds text and replaces it with another in the active worksheet",
    },
    # Word Online (Business)
    {
        "category": "Word Online (Business)",
        "friendly_name": "Convert Word Document to PDF",
        "description": "Gets a PDF version of the selected file",
    },
    {
        "category": "Word Online (Business)",
        "friendly_name": "Populate a Microsoft Word template",
        "description": "Reads a Microsoft Word template to then fill the template fields",
    },
    # SAP automation
    {
        "category": "SAP automation",
        "friendly_name": "Launch SAP",
        "description": "Opens the SAP GUI application and connect to an SAP system",
    },
    {
        "category": "SAP automation",
        "friendly_name": "Create new SAP session",
        "description": "Creates a new SAP session based on the same SAP instance",
    },
    {
        "category": "SAP automation",
        "friendly_name": "Select SAP menu item",
        "description": "Selects an SAP menu item in the window tool bar",
    },
    {
        "category": "SAP automation",
        "friendly_name": "Start SAP transaction",
        "description": "Opens a specific transaction code in existing session",
    },
    {
        "category": "SAP automation",
        "friendly_name": "End SAP transaction",
        "description": "Closes the SAP transaction in a specific SAP instance",
    },
    {
        "category": "SAP automation",
        "friendly_name": "Close SAP connection",
        "description": "Closes the SAP connection of the selected SAP instance",
    },
    {
        "category": "SAP automation",
        "friendly_name": "Click SAP UI element",
        "description": "Interacts through click action on any UI element of an SAP window",
    },
    {
        "category": "SAP automation",
        "friendly_name": "Get details of SAP UI element",
        "description": "Gets the value of an SAP UI element's attribute in an SAP window",
    },
    {
        "category": "SAP automation",
        "friendly_name": "Populate SAP text field in element",
        "description": "Fills a text box in an SAP window with the specified text",
    },
    # SAP automation - Advanced
    {
        "category": "SAP automation - Advanced",
        "friendly_name": "Attach",
        "description": "Attach the running SAP GUI application to an SAP instance",
    },
    # Power Automate secret variables
    {
        "category": "Power Automate secret variables",
        "friendly_name": "Get credential",
        "description": "Retrieves the values of a credential created through Power Automate's portal page",
    },
    # Variables - Data table
    {
        "category": "Variables - Data table",
        "friendly_name": "Create new data table",
        "description": "Creates a new data table variable",
    },
    {
        "category": "Variables - Data table",
        "friendly_name": "Insert row into data table",
        "description": "Inserts a row at the end or before a specific index value",
    },
    {
        "category": "Variables - Data table",
        "friendly_name": "Find or replace in data table",
        "description": "Finds and/or replaces data table values",
    },
    {
        "category": "Variables - Data table",
        "friendly_name": "Update data table item",
        "description": "Updates a data table row item on a defined column",
    },
    {
        "category": "Variables - Data table",
        "friendly_name": "Delete row from data table",
        "description": "Deletes a data table row item",
    },
    {
        "category": "Variables - Data table",
        "friendly_name": "Insert column into data table",
        "description": "Inserts a column at the end or before a specific index",
    },
    {
        "category": "Variables - Data table",
        "friendly_name": "Delete column from data table",
        "description": "Deletes a data table column at the specified index",
    },
    {
        "category": "Variables - Data table",
        "friendly_name": "Delete empty rows from data table",
        "description": "Deletes the rows of the data table that have all cells empty",
    },
    {
        "category": "Variables - Data table",
        "friendly_name": "Delete duplicate rows from data table",
        "description": "Deletes all the rows that are duplicate from the data table",
    },
    {
        "category": "Variables - Data table",
        "friendly_name": "Clear data table",
        "description": "Deletes all the rows of the data table, keeping table headers",
    },
    {
        "category": "Variables - Data table",
        "friendly_name": "Sort data table",
        "description": "Sorts the data table rows in ascending or descending order",
    },
    {
        "category": "Variables - Data table",
        "friendly_name": "Filter data table",
        "description": "Filters the data table rows based on the applied rules",
    },
    {
        "category": "Variables - Data table",
        "friendly_name": "Merge data tables",
        "description": "Merges two data tables together",
    },
    {
        "category": "Variables - Data table",
        "friendly_name": "Join data tables",
        "description": "Joins two data tables based on the specified join rule",
    },
    {
        "category": "Variables - Data table",
        "friendly_name": "Read from CSV text variable",
        "description": "Generates a data table from a CSV text",
    },
    {
        "category": "Variables - Data table",
        "friendly_name": "Convert data table to text",
        "description": "Converts a data table to a CSV text",
    },
    # Conditionals
    {
        "category": "Conditionals",
        "friendly_name": "If",
        "description": "Marks the beginning of a block of actions that is run if the condition is met",
    },
    {
        "category": "Conditionals",
        "friendly_name": "Else if",
        "description": "Marks the beginning of a block of actions that ran if conditions in preceding If statements aren't met",
    },
    {
        "category": "Conditionals",
        "friendly_name": "Else",
        "description": "Marks the beginning of a block of actions that ran if the condition specified in the preceding If statements aren't met",
    },
    {
        "category": "Conditionals",
        "friendly_name": "Switch",
        "description": "Dispatches execution to different parts of the switch body based on the value of the expression",
    },
    {
        "category": "Conditionals",
        "friendly_name": "Case",
        "description": "An expression that, if met, a block of actions associated with that particular case runs",
    },
    {
        "category": "Conditionals",
        "friendly_name": "Default case",
        "description": "A block of actions that is run, if no case expression has been met",
    },
    # Loops
    {
        "category": "Loops",
        "friendly_name": "Exit loop",
        "description": "Terminates the loop and the flow resumes at the next action",
    },
    {
        "category": "Loops",
        "friendly_name": "For each",
        "description": "Iterates over items in a list, data table or data row",
    },
    {
        "category": "Loops",
        "friendly_name": "Loop",
        "description": "Iterates a block of actions for a specified number of times",
    },
    {
        "category": "Loops",
        "friendly_name": "Loop condition",
        "description": "Iterates a block of actions as long as a specified condition proves to be true",
    },
    {
        "category": "Loops",
        "friendly_name": "Next loop",
        "description": "Forces the next iteration of the block to take place",
    },
    # Folder
    {
        "category": "Folder",
        "friendly_name": "If folder exists",
        "description": "Mark the beginning of a conditional block of actions depending on whether a folder exists",
    },
    {
        "category": "Folder",
        "friendly_name": "Get files in folder",
        "description": "Retrieve the list of files in a folder",
    },
    {
        "category": "Folder",
        "friendly_name": "Get subfolders in folder",
        "description": "Retrieve the list of subfolders in a folder",
    },
    {"category": "Folder", "friendly_name": "Create folder", "description": "Creates a new folder"},
    {
        "category": "Folder",
        "friendly_name": "Delete folder",
        "description": "Deletes an existing folder and its contents",
    },
    {
        "category": "Folder",
        "friendly_name": "Empty folder",
        "description": "Deletes all the contents of a folder without deleting the folder",
    },
    {
        "category": "Folder",
        "friendly_name": "Copy folder",
        "description": "Copies a folder into a destination folder",
    },
    {
        "category": "Folder",
        "friendly_name": "Move folder",
        "description": "Moves an existing folder into a destination folder",
    },
    {
        "category": "Folder",
        "friendly_name": "Rename folder",
        "description": "Changes the name of a folder",
    },
    {
        "category": "Folder",
        "friendly_name": "Get special folder",
        "description": "Retrieves the path of a Windows special folder",
    },
    # Compression
    {
        "category": "Compression",
        "friendly_name": "ZIP files",
        "description": "Compress one or more files or folders into a ZIP archive",
    },
    {
        "category": "Compression",
        "friendly_name": "Unzip files",
        "description": "Uncompress one or more files or folders contained in a ZIP archive",
    },
    # Workstation
    {
        "category": "Workstation",
        "friendly_name": "Print document",
        "description": "Prints a document on the default printer",
    },
    {
        "category": "Workstation",
        "friendly_name": "Get default printer",
        "description": "Gets the name of the default printer",
    },
    {
        "category": "Workstation",
        "friendly_name": "Set default printer",
        "description": "Sets a printer as the default printer",
    },
    {
        "category": "Workstation",
        "friendly_name": "Log off user",
        "description": "Logs off the current user",
    },
    {
        "category": "Workstation",
        "friendly_name": "Shutdown computer",
        "description": "Instructs the computer to shut down",
    },
    {
        "category": "Workstation",
        "friendly_name": "Show desktop",
        "description": "Shows the desktop",
    },
    {
        "category": "Workstation",
        "friendly_name": "Lock workstation",
        "description": "Locks the workstation's display to protect it from unauthorized use",
    },
    {
        "category": "Workstation",
        "friendly_name": "Play sound",
        "description": "Plays a system sound or a wav file",
    },
    {
        "category": "Workstation",
        "friendly_name": "Empty recycle bin",
        "description": "Deletes all files from the windows recycle bin",
    },
    {
        "category": "Workstation",
        "friendly_name": "Take screenshot",
        "description": "Takes a screenshot of the foreground window or specified screen",
    },
    {
        "category": "Workstation",
        "friendly_name": "Control screen saver",
        "description": "Enables, disables, starts or stops the screensaver",
    },
    {
        "category": "Workstation",
        "friendly_name": "Get screen resolution",
        "description": "Gets the width, height, bit count and frequency of a selected monitor",
    },
    {
        "category": "Workstation",
        "friendly_name": "Set screen resolution",
        "description": "Sets the width, height, bit count and frequency of a selected monitor",
    },
    # System
    {
        "category": "System",
        "friendly_name": "If process",
        "description": "Marks the beginning of a conditional block depending on whether a process is running",
    },
    {
        "category": "System",
        "friendly_name": "Wait for process",
        "description": "Suspends the execution until a process starts or stops",
    },
    {
        "category": "System",
        "friendly_name": "Run application",
        "description": "Executes an application or opens a document",
    },
    {
        "category": "System",
        "friendly_name": "Terminate process",
        "description": "Immediately stops a running process",
    },
    {
        "category": "System",
        "friendly_name": "Ping",
        "description": "Sends a message to determine whether a remote computer is accessible",
    },
    {
        "category": "System",
        "friendly_name": "Set Windows environment variable",
        "description": "Sets an environment variable to a given value",
    },
    {
        "category": "System",
        "friendly_name": "Get Windows environment variable",
        "description": "Retrieves the value of an environment variable",
    },
    {
        "category": "System",
        "friendly_name": "Delete Windows environment variable",
        "description": "Deletes an environment variable from a given scope",
    },
    # PDF
    {
        "category": "PDF",
        "friendly_name": "Extract text from PDF",
        "description": "Extracts text from a PDF file",
    },
    {
        "category": "PDF",
        "friendly_name": "Extract tables from PDF",
        "description": "Extracts tables from a PDF file",
    },
    {
        "category": "PDF",
        "friendly_name": "Extract images from PDF",
        "description": "Extracts images from a PDF file",
    },
    {
        "category": "PDF",
        "friendly_name": "Extract PDF file pages to new PDF file",
        "description": "Extracts pages from a PDF file to a new PDF file",
    },
    {
        "category": "PDF",
        "friendly_name": "Merge PDF files",
        "description": "Merges multiple PDF files into a new one",
    },
    # XML
    {
        "category": "XML",
        "friendly_name": "Read XML from file",
        "description": "Reads the contents of an XML file into a variable",
    },
    {
        "category": "XML",
        "friendly_name": "Write XML to file",
        "description": "Writes the contents of an XML node variable into a file",
    },
    {
        "category": "XML",
        "friendly_name": "Execute XPath expression",
        "description": "Extracts values from an XML document based on the XPath query",
    },
    {
        "category": "XML",
        "friendly_name": "Get XML element attribute",
        "description": "Gets the value of an attribute of an XML element",
    },
    {
        "category": "XML",
        "friendly_name": "Set XML element attribute",
        "description": "Sets the value of an attribute of an XML element",
    },
    {
        "category": "XML",
        "friendly_name": "Remove XML element attribute",
        "description": "Removes an attribute from an XML element",
    },
    {
        "category": "XML",
        "friendly_name": "Get XML element value",
        "description": "Gets the value of an XML element",
    },
    {
        "category": "XML",
        "friendly_name": "Set XML element value",
        "description": "Sets the value of an XML element",
    },
    {
        "category": "XML",
        "friendly_name": "Insert XML element",
        "description": "Inserts a new XML element into an XML document",
    },
    {
        "category": "XML",
        "friendly_name": "Remove XML element",
        "description": "Removes one or more XML elements from an XML document",
    },
    # Database
    {
        "category": "Database",
        "friendly_name": "Open SQL connection",
        "description": "Opens a new connection to a database",
    },
    {
        "category": "Database",
        "friendly_name": "Execute SQL statement",
        "description": "Connects to a database and executes a SQL statement",
    },
    {
        "category": "Database",
        "friendly_name": "Close SQL connection",
        "description": "Closes an open connection to a database",
    },
    # CMD session
    {
        "category": "CMD session",
        "friendly_name": "Open CMD session",
        "description": "Opens a new CMD session",
    },
    {
        "category": "CMD session",
        "friendly_name": "Read from CMD session",
        "description": "Reads the output of a CMD session",
    },
    {
        "category": "CMD session",
        "friendly_name": "Write to CMD session",
        "description": "Executes a command on an open CMD session",
    },
    {
        "category": "CMD session",
        "friendly_name": "Wait for text on CMD session",
        "description": "Waits for a specific text on a previously opened CMD session",
    },
    {
        "category": "CMD session",
        "friendly_name": "Close CMD session",
        "description": "Closes a previously opened CMD session",
    },
    # Windows services
    {
        "category": "Windows services",
        "friendly_name": "If service",
        "description": "Marks the beginning of a conditional block depending on whether a service is running",
    },
    {
        "category": "Windows services",
        "friendly_name": "Wait for service",
        "description": "Suspends execution until a service is running, paused or stopped",
    },
    {
        "category": "Windows services",
        "friendly_name": "Start service",
        "description": "Starts a stopped Windows service",
    },
    {
        "category": "Windows services",
        "friendly_name": "Stop service",
        "description": "Stops a running Windows service",
    },
    {
        "category": "Windows services",
        "friendly_name": "Pause service",
        "description": "Pauses a running Windows service",
    },
    {
        "category": "Windows services",
        "friendly_name": "Resume service",
        "description": "Resumes a paused Windows service",
    },
    # OCR
    {
        "category": "OCR",
        "friendly_name": "If text on screen (OCR)",
        "description": "Marks the beginning of a conditional block depending on whether a given text appears on the screen",
    },
    {
        "category": "OCR",
        "friendly_name": "Wait for text on screen (OCR)",
        "description": "Waits until a specific text appears/disappears on the screen using OCR",
    },
    {
        "category": "OCR",
        "friendly_name": "Extract text with OCR",
        "description": "Extracts text from a given source using the given OCR engine",
    },
    # Text
    {
        "category": "Text",
        "friendly_name": "Append line to text",
        "description": "Appends a new line of text to a text value",
    },
    {
        "category": "Text",
        "friendly_name": "Get subtext",
        "description": "Retrieves a subtext from a text value",
    },
    {
        "category": "Text",
        "friendly_name": "Crop text",
        "description": "Retrieves a text value that occurs before, after or between the specified text flags",
    },
    {
        "category": "Text",
        "friendly_name": "Pad text",
        "description": "Creates a fixed length text by adding characters to the left or right",
    },
    {
        "category": "Text",
        "friendly_name": "Trim text",
        "description": "Removes all occurrences of white space characters from the beginning and/or end",
    },
    {
        "category": "Text",
        "friendly_name": "Reverse text",
        "description": "Reverses the order of letters in a text string",
    },
    {
        "category": "Text",
        "friendly_name": "Change text case",
        "description": "Changes the casing of a text to uppercase, lowercase, title case or sentence case",
    },
    {
        "category": "Text",
        "friendly_name": "Convert text to number",
        "description": "Converts a text representation of a number to a numeric value",
    },
    {
        "category": "Text",
        "friendly_name": "Convert number to text",
        "description": "Converts a number to text using a specified format",
    },
    {
        "category": "Text",
        "friendly_name": "Convert text to datetime",
        "description": "Converts a text representation of a date and/or time value to a datetime",
    },
    {
        "category": "Text",
        "friendly_name": "Convert datetime to text",
        "description": "Converts a datetime value to text using a specified custom format",
    },
    {
        "category": "Text",
        "friendly_name": "Create random text",
        "description": "Generates a text of specified length consisting of random characters",
    },
    {
        "category": "Text",
        "friendly_name": "Join text",
        "description": "Converts a list into a text value by separating its items with a delimiter",
    },
    {
        "category": "Text",
        "friendly_name": "Split text",
        "description": "Creates a list containing the substrings of a text separated by a delimiter",
    },
    {
        "category": "Text",
        "friendly_name": "Parse text",
        "description": "Parses a text to find the first or all occurrences of a specified subtext",
    },
    {
        "category": "Text",
        "friendly_name": "Replace text",
        "description": "Replaces all occurrences of a specified subtext with another text",
    },
    {
        "category": "Text",
        "friendly_name": "Escape text for regular expression",
        "description": "Escapes a minimal set of characters by replacing them with their escape codes",
    },
    {
        "category": "Text",
        "friendly_name": "Recognize entities in text",
        "description": "Recognizes entities in text, such as numbers, units, data/time and others",
    },
    {
        "category": "Text",
        "friendly_name": "Create HTML content",
        "description": "Generates rich HTML content and stores it in a variable",
    },
    # Date time
    {
        "category": "Date time",
        "friendly_name": "Add to datetime",
        "description": "Adds or subtracts a specific number of seconds, minutes, hours or days to a datetime value",
    },
    {
        "category": "Date time",
        "friendly_name": "Subtract dates",
        "description": "Finds the time difference between two given dates in days, hours, minutes, or seconds",
    },
    {
        "category": "Date time",
        "friendly_name": "Get current date and time",
        "description": "Retrieves the current date or the current date and time",
    },
    # Scripting
    {
        "category": "Scripting",
        "friendly_name": "Run DOS command",
        "description": "Executes a DOS command or console application and retrieves its output",
    },
    {
        "category": "Scripting",
        "friendly_name": "Run VBScript",
        "description": "Executes some custom VBScript code and retrieves its output",
    },
    {
        "category": "Scripting",
        "friendly_name": "Run JavaScript",
        "description": "Executes some custom JavaScript code and retrieves its output",
    },
    {
        "category": "Scripting",
        "friendly_name": "Run PowerShell script",
        "description": "Executes some custom PowerShell script and retrieves its output",
    },
    {
        "category": "Scripting",
        "friendly_name": "Run Python script",
        "description": "Executes Python 2 script code and retrieves its output",
    },
    {
        "category": "Scripting",
        "friendly_name": "Run .NET script",
        "description": "Executes a user provided .NET script and stores its output",
    },
    # FTP
    {
        "category": "FTP",
        "friendly_name": "Open FTP connection",
        "description": "Establishes a specific connection to a remote FTP server",
    },
    {
        "category": "FTP",
        "friendly_name": "Open secure FTP connection",
        "description": "Establishes a specific secure connection to a remote FTP server",
    },
    {
        "category": "FTP",
        "friendly_name": "Close connection",
        "description": "Closes an open FTP connection",
    },
    {
        "category": "FTP",
        "friendly_name": "Change working directory",
        "description": "Sets the current working directory for an FTP connection",
    },
    {
        "category": "FTP",
        "friendly_name": "Download file(s) from FTP",
        "description": "Downloads one or more files from an FTP server",
    },
    {
        "category": "FTP",
        "friendly_name": "Download folder(s) from FTP",
        "description": "Downloads one or more folders from an FTP server",
    },
    {
        "category": "FTP",
        "friendly_name": "Upload File(s) to FTP",
        "description": "Uploads one or more files to an FTP server",
    },
    {
        "category": "FTP",
        "friendly_name": "Upload folder(s) to FTP",
        "description": "Uploads one or more folders to an FTP server",
    },
    {
        "category": "FTP",
        "friendly_name": "Delete FTP file",
        "description": "Deletes one or more files from an FTP server",
    },
    {
        "category": "FTP",
        "friendly_name": "Rename FTP File",
        "description": "Renames a file that resides on an FTP server",
    },
    {
        "category": "FTP",
        "friendly_name": "Create FTP directory",
        "description": "Creates a directory on an FTP server",
    },
    {
        "category": "FTP",
        "friendly_name": "Delete FTP directory",
        "description": "Deletes a directory from an FTP server",
    },
    {
        "category": "FTP",
        "friendly_name": "Invoke FTP command",
        "description": "Invokes the given literal FTP command on the server",
    },
    {
        "category": "FTP",
        "friendly_name": "Synchronize directories",
        "description": "Synchronizes the files and subdirectories of a given Folder with remote FTP",
    },
    # AWS - EC2
    {
        "category": "AWS - EC2",
        "friendly_name": "Create EC2 session",
        "description": "Creates an EC2 client to automate EC2 web services",
    },
    {
        "category": "AWS - EC2",
        "friendly_name": "End EC2 session",
        "description": "Disposes an open EC2 client",
    },
    # AWS - EC2 - Instances
    {
        "category": "AWS - EC2 - Instances",
        "friendly_name": "Start EC2 instance",
        "description": "Starts EC2 instance(s)",
    },
    {
        "category": "AWS - EC2 - Instances",
        "friendly_name": "Stop EC2 instance",
        "description": "Stops EC2 instance(s)",
    },
    {
        "category": "AWS - EC2 - Instances",
        "friendly_name": "Reboot EC2 instance",
        "description": "Reboots EC2 instance(s)",
    },
    {
        "category": "AWS - EC2 - Instances",
        "friendly_name": "Get available EC2 instances",
        "description": "Gets information for the relevant EC2 instances",
    },
    {
        "category": "AWS - EC2 - Instances",
        "friendly_name": "Describe instances",
        "description": "Returns all the information for the specified EC2 instance(s)",
    },
    # AWS - EC2 - Snapshots
    {
        "category": "AWS - EC2 - Snapshots",
        "friendly_name": "Create snapshot",
        "description": "Creates a snapshot of an EBS volume and stores it in Amazon S3",
    },
    {
        "category": "AWS - EC2 - Snapshots",
        "friendly_name": "Describe snapshots",
        "description": "Describes the specified EBS snapshots available",
    },
    {
        "category": "AWS - EC2 - Snapshots",
        "friendly_name": "Delete snapshot",
        "description": "Deletes the specified snapshot",
    },
    # AWS - EC2 - Volumes
    {
        "category": "AWS - EC2 - Volumes",
        "friendly_name": "Create volume",
        "description": "Creates an EBS volume",
    },
    {
        "category": "AWS - EC2 - Volumes",
        "friendly_name": "Attach volume",
        "description": "Attaches an EBS volume to an EC2 instance",
    },
    {
        "category": "AWS - EC2 - Volumes",
        "friendly_name": "Detach volume",
        "description": "Detaches an EBS volume from an EC2 instance",
    },
    {
        "category": "AWS - EC2 - Volumes",
        "friendly_name": "Describe volumes",
        "description": "Describes the specified EBS volumes",
    },
    {
        "category": "AWS - EC2 - Volumes",
        "friendly_name": "Delete volume",
        "description": "Deletes the specified EBS volume",
    },
    # Active Directory
    {
        "category": "Active Directory",
        "friendly_name": "Connect to server",
        "description": "Connects to an Active Directory server",
    },
    {
        "category": "Active Directory",
        "friendly_name": "Close connection",
        "description": "Closes the connection with the Active Directory server",
    },
    # Active Directory - User
    {
        "category": "Active Directory - User",
        "friendly_name": "Create user",
        "description": "Creates a user in the Active Directory",
    },
    {
        "category": "Active Directory - User",
        "friendly_name": "Get user info",
        "description": "Gets a user's information in the Active Directory",
    },
    {
        "category": "Active Directory - User",
        "friendly_name": "Modify user",
        "description": "Modifies a user in the Active Directory",
    },
    {
        "category": "Active Directory - User",
        "friendly_name": "Unlock user",
        "description": "Unlocks an Active Directory user",
    },
    {
        "category": "Active Directory - User",
        "friendly_name": "Update user info",
        "description": "Updates a user's information in the Active Directory",
    },
    # Active Directory - Group
    {
        "category": "Active Directory - Group",
        "friendly_name": "Create group",
        "description": "Creates a group in the Active Directory",
    },
    {
        "category": "Active Directory - Group",
        "friendly_name": "Get group info",
        "description": "Gets information about a group from the Active Directory server",
    },
    {
        "category": "Active Directory - Group",
        "friendly_name": "Get group members",
        "description": "Gets the members of a group in the Active Directory",
    },
    {
        "category": "Active Directory - Group",
        "friendly_name": "Modify group",
        "description": "Modifies a group in the Active Directory",
    },
    # Active Directory - Object
    {
        "category": "Active Directory - Object",
        "friendly_name": "Create object",
        "description": "Creates an object in the Active Directory",
    },
    {
        "category": "Active Directory - Object",
        "friendly_name": "Delete object",
        "description": "Deletes an object in the Active Directory",
    },
    {
        "category": "Active Directory - Object",
        "friendly_name": "Move object",
        "description": "Moves an object in the Active Directory",
    },
    {
        "category": "Active Directory - Object",
        "friendly_name": "Rename object",
        "description": "Renames an object in the Active Directory",
    },
    # Terminal emulation
    {
        "category": "Terminal emulation",
        "friendly_name": "Open terminal session",
        "description": "Opens a new terminal session",
    },
    {
        "category": "Terminal emulation",
        "friendly_name": "Close terminal session",
        "description": "Closes an open terminal session",
    },
    {
        "category": "Terminal emulation",
        "friendly_name": "Move cursor on terminal session",
        "description": "Moves the terminal's cursor on the specified position",
    },
    {
        "category": "Terminal emulation",
        "friendly_name": "Get text from terminal session",
        "description": "Gets text from a terminal session",
    },
    {
        "category": "Terminal emulation",
        "friendly_name": "Set text on terminal session",
        "description": "Sets text on a terminal session",
    },
    {
        "category": "Terminal emulation",
        "friendly_name": "Send key to terminal session",
        "description": "Sends a control key to a terminal session",
    },
    {
        "category": "Terminal emulation",
        "friendly_name": "Wait for text on terminal session",
        "description": "Waits for a specific text to appear on a terminal session",
    },
    {
        "category": "Terminal emulation",
        "friendly_name": "Search for text on terminal session",
        "description": "Searches for all occurrences of a specific text on a terminal session",
    },
    # IBM cognitive - Document conversion
    {
        "category": "IBM cognitive - Document conversion",
        "friendly_name": "Convert document",
        "description": "Invokes the IBM service named 'Convert Document'",
    },
    # IBM cognitive - Visual recognition
    {
        "category": "IBM cognitive - Visual recognition",
        "friendly_name": "Classify Image",
        "description": "Invokes the IBM service named 'Classify Image'",
    },
    # IBM cognitive - Language translator
    {
        "category": "IBM cognitive - Language translator",
        "friendly_name": "Translate",
        "description": "Invokes the IBM service named 'Translate'",
    },
    {
        "category": "IBM cognitive - Language translator",
        "friendly_name": "Identify language",
        "description": "Invokes the IBM service named 'Identify Language'",
    },
    # IBM cognitive - Tone analyzer
    {
        "category": "IBM cognitive - Tone analyzer",
        "friendly_name": "Analyze tone",
        "description": "Invokes the IBM service named 'Analyze Tone'",
    },
    # Microsoft cognitive - Bing spell check
    {
        "category": "Microsoft cognitive - Bing spell check",
        "friendly_name": "Spell check",
        "description": "Invokes the Microsoft Cognitive service named 'Bing Spell Check'",
    },
    # Microsoft cognitive - Computer vision
    {
        "category": "Microsoft cognitive - Computer vision",
        "friendly_name": "Analyze image",
        "description": "Invokes the Microsoft Cognitive service named 'Analyze Image'",
    },
    {
        "category": "Microsoft cognitive - Computer vision",
        "friendly_name": "Describe image",
        "description": "Invokes the Microsoft Cognitive service named 'Describe Image'",
    },
    {
        "category": "Microsoft cognitive - Computer vision",
        "friendly_name": "OCR",
        "description": "Invokes the Microsoft Cognitive service named 'OCR'",
    },
    {
        "category": "Microsoft cognitive - Computer vision",
        "friendly_name": "Tag image",
        "description": "Invokes the Microsoft Cognitive service named 'Tag Image'",
    },
    # Microsoft cognitive - Text Analytics
    {
        "category": "Microsoft cognitive - Text Analytics",
        "friendly_name": "Detect language",
        "description": "Invokes the Microsoft Cognitive service named 'Text Analytics - Detect Language'",
    },
    {
        "category": "Microsoft cognitive - Text Analytics",
        "friendly_name": "Key phrases",
        "description": "Invokes the Microsoft Cognitive service named 'Text Analytics - Key Phrases'",
    },
    {
        "category": "Microsoft cognitive - Text Analytics",
        "friendly_name": "Sentiment",
        "description": "Invokes the Microsoft Cognitive service named 'Text Analytics - Sentiment'",
    },
    # Clipboard
    {
        "category": "Clipboard",
        "friendly_name": "Get clipboard text",
        "description": "Gets clipboard text",
    },
    {
        "category": "Clipboard",
        "friendly_name": "Set clipboard Text",
        "description": "Sets clipboard text",
    },
    {
        "category": "Clipboard",
        "friendly_name": "Clear clipboard contents",
        "description": "Clears clipboard contents",
    },
    # AI Builder
    {
        "category": "AI Builder",
        "friendly_name": "Create text with GPT",
        "description": "Gets a response generated by GPT",
    },
    # Office 365 Outlook (extensive)
    {
        "category": "Office 365 Outlook",
        "friendly_name": "Create contact (V2)",
        "description": "Creates a new contact in a contacts folder",
    },
    {
        "category": "Office 365 Outlook",
        "friendly_name": "Create event (V4)",
        "description": "Creates a new event in a calendar",
    },
    {
        "category": "Office 365 Outlook",
        "friendly_name": "Delete contact (V2)",
        "description": "Deletes a contact from a contacts folder",
    },
    {
        "category": "Office 365 Outlook",
        "friendly_name": "Delete event (V2)",
        "description": "Deletes an event in a calendar",
    },
    {
        "category": "Office 365 Outlook",
        "friendly_name": "Export email (V2)",
        "description": "Exports the content of the email in the EML file format",
    },
    {
        "category": "Office 365 Outlook",
        "friendly_name": "Find meeting times (V2)",
        "description": "Finds meeting time suggestions based on organizer and attendee availability",
    },
    {
        "category": "Office 365 Outlook",
        "friendly_name": "Flag email (V2)",
        "description": "Updates an email flag",
    },
    {
        "category": "Office 365 Outlook",
        "friendly_name": "Forward an email (V2)",
        "description": "Forwards an email",
    },
    {
        "category": "Office 365 Outlook",
        "friendly_name": "Get Attachment (V2)",
        "description": "Gets an email attachment by id",
    },
    {
        "category": "Office 365 Outlook",
        "friendly_name": "Get calendar view of events (V3)",
        "description": "Gets all events in a calendar using Graph API",
    },
    {
        "category": "Office 365 Outlook",
        "friendly_name": "Get calendars (V2)",
        "description": "Lists available calendars",
    },
    {
        "category": "Office 365 Outlook",
        "friendly_name": "Get contact (V2)",
        "description": "Gets a specific contact from a contacts folder",
    },
    {
        "category": "Office 365 Outlook",
        "friendly_name": "Get contacts (V2)",
        "description": "Gets contacts from a contacts folder",
    },
    {
        "category": "Office 365 Outlook",
        "friendly_name": "Get email (V2)",
        "description": "Gets an email by id",
    },
    {
        "category": "Office 365 Outlook",
        "friendly_name": "Get emails (V3)",
        "description": "Gets emails from a folder via graph apis",
    },
    {
        "category": "Office 365 Outlook",
        "friendly_name": "Get event (V3)",
        "description": "Gets a specific event from a calendar using Graph API",
    },
    {
        "category": "Office 365 Outlook",
        "friendly_name": "Get events (V4)",
        "description": "Gets events from a calendar using Graph API",
    },
    {
        "category": "Office 365 Outlook",
        "friendly_name": "Get room lists (V2)",
        "description": "Gets all the room lists defined in the user's tenant",
    },
    {
        "category": "Office 365 Outlook",
        "friendly_name": "Get rooms (V2)",
        "description": "Gets all the meeting rooms defined in the user's tenant",
    },
    {
        "category": "Office 365 Outlook",
        "friendly_name": "Get rooms in room list (V2)",
        "description": "Gets the meeting rooms in a specific room list",
    },
    {
        "category": "Office 365 Outlook",
        "friendly_name": "Mark as read or unread (V3)",
        "description": "Marks an email as read/unread",
    },
    {
        "category": "Office 365 Outlook",
        "friendly_name": "Move email (V2)",
        "description": "Moves an email to the specified folder",
    },
    {
        "category": "Office 365 Outlook",
        "friendly_name": "Reply to email (V3)",
        "description": "Replies to an email",
    },
    {
        "category": "Office 365 Outlook",
        "friendly_name": "Respond to an event invite (V2)",
        "description": "Responds to an event invite",
    },
    {
        "category": "Office 365 Outlook",
        "friendly_name": "Send an email (V2)",
        "description": "Sends an email message",
    },
    {
        "category": "Office 365 Outlook",
        "friendly_name": "Send an email from a shared mailbox (V2)",
        "description": "Sends an email from a shared mailbox",
    },
    {
        "category": "Office 365 Outlook",
        "friendly_name": "Set up automatic replies (V2)",
        "description": "Sets the automatic replies setting for mailbox",
    },
    {
        "category": "Office 365 Outlook",
        "friendly_name": "Update contact (V2)",
        "description": "Updates a contact in a contacts folder",
    },
    {
        "category": "Office 365 Outlook",
        "friendly_name": "Update event (V4)",
        "description": "Updates an event in a calendar using Graph API",
    },
    {
        "category": "Office 365 Outlook",
        "friendly_name": "Send an HTTP request",
        "description": "Constructs a Microsoft Graph REST API request",
    },
    # Microsoft Teams
    {
        "category": "Microsoft Teams",
        "friendly_name": "Add a member to a tag",
        "description": "Adds a user to a tags",
    },
    {
        "category": "Microsoft Teams",
        "friendly_name": "Add a member to a team",
        "description": "Adds a member to a team",
    },
    {
        "category": "Microsoft Teams",
        "friendly_name": "Create a channel",
        "description": "Creates a new channel for a specific Team",
    },
    {
        "category": "Microsoft Teams",
        "friendly_name": "Create a chat",
        "description": "Creates a one on one or group chat",
    },
    {
        "category": "Microsoft Teams",
        "friendly_name": "Create a tag for a team",
        "description": "Creates a tag",
    },
    {
        "category": "Microsoft Teams",
        "friendly_name": "Create a team",
        "description": "Creates a new team",
    },
    {
        "category": "Microsoft Teams",
        "friendly_name": "Create a Teams meeting",
        "description": "Creates a meeting with a link at the bottom of the invite",
    },
    {
        "category": "Microsoft Teams",
        "friendly_name": "Delete a member from a tag",
        "description": "Deletes a member from a tag",
    },
    {
        "category": "Microsoft Teams",
        "friendly_name": "Delete a tag",
        "description": "Deletes a tag",
    },
    {
        "category": "Microsoft Teams",
        "friendly_name": "Get a team",
        "description": "Returns details for a team using the team's unique ID",
    },
    {
        "category": "Microsoft Teams",
        "friendly_name": "Get an mention token for a tag",
        "description": "Creates a token that can be inserted into a message",
    },
    {
        "category": "Microsoft Teams",
        "friendly_name": "Get an mention token for a user",
        "description": "Creates a token for @mentioning a user",
    },
    {
        "category": "Microsoft Teams",
        "friendly_name": "Get message details",
        "description": "Gets details of a message in a chat or channel",
    },
    {
        "category": "Microsoft Teams",
        "friendly_name": "Get messages",
        "description": "Gets messages from a channel in a specific Team",
    },
    {
        "category": "Microsoft Teams",
        "friendly_name": "List all tags for a team",
        "description": "Retrieves a list of tags",
    },
    {
        "category": "Microsoft Teams",
        "friendly_name": "List channels",
        "description": "Retrieves a list of all the channels for a specific Team",
    },
    {
        "category": "Microsoft Teams",
        "friendly_name": "List chats",
        "description": "Retrieves a list of recent chats",
    },
    {
        "category": "Microsoft Teams",
        "friendly_name": "List members",
        "description": "Lists members based on a threadtype",
    },
    {
        "category": "Microsoft Teams",
        "friendly_name": "List teams",
        "description": "Retrieves a list of all the Teams",
    },
    {
        "category": "Microsoft Teams",
        "friendly_name": "List the members for a tag",
        "description": "Lists the members for a tag",
    },
    {
        "category": "Microsoft Teams",
        "friendly_name": "Post a feed notification",
        "description": "Posts a feed notification",
    },
    {
        "category": "Microsoft Teams",
        "friendly_name": "Post card in a chat or channel",
        "description": "Posts a card to a chat or a channel",
    },
    {
        "category": "Microsoft Teams",
        "friendly_name": "Post message in a chat or channel",
        "description": "Posts a message to a chat or a channel",
    },
    {
        "category": "Microsoft Teams",
        "friendly_name": "Reply with a message in a channel",
        "description": "Replies with a message in a channel",
    },
    {
        "category": "Microsoft Teams",
        "friendly_name": "Reply with adaptive card in a channel",
        "description": "Replies with an adaptive card to a channel",
    },
    {
        "category": "Microsoft Teams",
        "friendly_name": "Update an adaptive card in a chat or channel",
        "description": "Updates an existing adaptive card",
    },
    {
        "category": "Microsoft Teams",
        "friendly_name": "Send a Microsoft Graph HTTP request",
        "description": "Constructs a Microsoft Graph REST API request",
    },
    # Microsoft Forms
    {
        "category": "Microsoft Forms",
        "friendly_name": "Get response details",
        "description": "Retrieves a form response",
    },
    # Microsoft Dataverse
    {
        "category": "Microsoft Dataverse",
        "friendly_name": "Add a new row to selected environment",
        "description": "Creates a new row in a table in a Power Platform environment",
    },
    {
        "category": "Microsoft Dataverse",
        "friendly_name": "Delete a row from selected environment",
        "description": "Deletes a row from a table in a Power Platform environment",
    },
    {
        "category": "Microsoft Dataverse",
        "friendly_name": "Download a file or an image from selected environment",
        "description": "Retrieves file or image data from a row",
    },
    {
        "category": "Microsoft Dataverse",
        "friendly_name": "Get a row by ID from selected environment",
        "description": "Gets a row from a table in a Power Platform environment",
    },
    {
        "category": "Microsoft Dataverse",
        "friendly_name": "List rows from selected environment",
        "description": "Lists rows from a table in a Power Platform environment",
    },
    {
        "category": "Microsoft Dataverse",
        "friendly_name": "Perform a bound action in selected environment",
        "description": "Runs a Dataverse action bound to a table",
    },
    {
        "category": "Microsoft Dataverse",
        "friendly_name": "Perform an unbound action in selected environment",
        "description": "Runs a global Dataverse action in a Power Platform environment",
    },
    {
        "category": "Microsoft Dataverse",
        "friendly_name": "Relate rows in selected environment",
        "description": "Associates individual rows in tables that have a one-to-many relationship",
    },
    {
        "category": "Microsoft Dataverse",
        "friendly_name": "Remove the association between individual rows",
        "description": "Removes the association between individual rows",
    },
    {
        "category": "Microsoft Dataverse",
        "friendly_name": "Upload a file or an image to selected environment",
        "description": "Uploads a file or an image to selected environment",
    },
    {
        "category": "Microsoft Dataverse",
        "friendly_name": "Update file or image content in a row",
        "description": "Updates file or image content in a row",
    },
    {
        "category": "Microsoft Dataverse",
        "friendly_name": "Upsert a row in selected environment",
        "description": "Updates or adds (upsert) a row in a table",
    },
    # Flow control
    {"category": "Flow control", "friendly_name": "Comment", "description": "User comment"},
    {
        "category": "Flow control",
        "friendly_name": "End",
        "description": "Set rules and manage the course of the flow",
    },
    {
        "category": "Flow control",
        "friendly_name": "Exit subflow",
        "description": "Exits current subflow and returns to the point it was called",
    },
    {
        "category": "Flow control",
        "friendly_name": "Get last error",
        "description": "Retrieves the last error that occurred in the flow",
    },
    {
        "category": "Flow control",
        "friendly_name": "Go to",
        "description": "Transfers the flow of execution to another point",
    },
    {
        "category": "Flow control",
        "friendly_name": "Label",
        "description": "Acts as the destination of a go to statement",
    },
    {
        "category": "Flow control",
        "friendly_name": "On block error",
        "description": "Marks the beginning of a block to handle actions errors",
    },
    {
        "category": "Flow control",
        "friendly_name": "Run subflow",
        "description": "Runs a subflow specifying any required arguments",
    },
    {
        "category": "Flow control",
        "friendly_name": "Stop flow",
        "description": "Terminates the flow",
    },
    {
        "category": "Flow control",
        "friendly_name": "Wait",
        "description": "Suspends the execution of the flow for a specified amount of seconds",
    },
    {
        "category": "Flow control",
        "friendly_name": "Region",
        "description": "Marks the beginning of a group of actions",
    },
    {
        "category": "Flow control",
        "friendly_name": "End region",
        "description": "Marks the end of a group of actions",
    },
    {
        "category": "Flow control",
        "friendly_name": "Run flow",
        "description": "Runs desktop flow which can receive input variables",
    },
    # File
    {
        "category": "File",
        "friendly_name": "If file exists",
        "description": "Marks the beginning of a conditional block depending on whether a file exists",
    },
    {
        "category": "File",
        "friendly_name": "Wait for file",
        "description": "Suspends execution until a file is created or deleted",
    },
    {
        "category": "File",
        "friendly_name": "Copy file(s)",
        "description": "Copies one or more files into a destination folder",
    },
    {
        "category": "File",
        "friendly_name": "Move file(s)",
        "description": "Moves one or more files into a destination folder",
    },
    {
        "category": "File",
        "friendly_name": "Delete file(s)",
        "description": "Deletes one or more files",
    },
    {
        "category": "File",
        "friendly_name": "Rename file(s)",
        "description": "Changes the name of one or more files",
    },
    {
        "category": "File",
        "friendly_name": "Read text from file",
        "description": "Reads the contents of a text file",
    },
    {
        "category": "File",
        "friendly_name": "Write text to file",
        "description": "Writes or appends text to a file",
    },
    {
        "category": "File",
        "friendly_name": "Read from CSV file",
        "description": "Reads a CSV file into a data table",
    },
    {
        "category": "File",
        "friendly_name": "Write to CSV file",
        "description": "Writes a data table, data row or list to a CSV file",
    },
    {
        "category": "File",
        "friendly_name": "Get file path part",
        "description": "Retrieves one or more parts from a text that represents a file path",
    },
    {
        "category": "File",
        "friendly_name": "Get temporary file",
        "description": "Creates a uniquely named, empty temporary file on disk",
    },
    {
        "category": "File",
        "friendly_name": "Convert file to Base64",
        "description": "Converts a file to Base64 encoded text",
    },
    {
        "category": "File",
        "friendly_name": "Convert Base64 to file",
        "description": "Converts a Base64 encoded text to file",
    },
    {
        "category": "File",
        "friendly_name": "Convert file to binary data",
        "description": "Converts a file to binary data",
    },
    {
        "category": "File",
        "friendly_name": "Convert binary data to file",
        "description": "Converts binary data to file",
    },
    # Email (IMAP)
    {
        "category": "Email",
        "friendly_name": "Retrieve email messages",
        "description": "Retrieves email messages from an IMAP server",
    },
    {
        "category": "Email",
        "friendly_name": "Process email messages",
        "description": "Moves, deletes or marks as unread an email",
    },
    {
        "category": "Email",
        "friendly_name": "Send email",
        "description": "Creates and sends a new email message",
    },
    # Exchange Server
    {
        "category": "Exchange Server",
        "friendly_name": "Connect to Exchange server",
        "description": "Opens a new connection to an Exchange server",
    },
    {
        "category": "Exchange Server",
        "friendly_name": "Retrieve email messages",
        "description": "Retrieves email messages from the specified Exchange server",
    },
    {
        "category": "Exchange Server",
        "friendly_name": "Retrieve Exchange email messages",
        "description": "Retrieves email messages from the specified Exchange server",
    },
    {
        "category": "Exchange Server",
        "friendly_name": "Send Exchange email message",
        "description": "Creates and sends a new email message",
    },
    {
        "category": "Exchange Server",
        "friendly_name": "Process Exchange email messages",
        "description": "Moves, deletes or marks as unread an email message",
    },
    # Outlook
    {
        "category": "Outlook",
        "friendly_name": "Launch Outlook",
        "description": "Launches Outlook and creates a new Outlook instance",
    },
    {
        "category": "Outlook",
        "friendly_name": "Retrieve email messages from Outlook",
        "description": "Retrieves email messages from an Outlook account",
    },
    {
        "category": "Outlook",
        "friendly_name": "Send email through Outlook",
        "description": "Creates and sends a new email message through Outlook",
    },
    {
        "category": "Outlook",
        "friendly_name": "Process email messages in Outlook",
        "description": "Moves or deletes an email retrieved by a Retrieve emails action",
    },
    {
        "category": "Outlook",
        "friendly_name": "Save Outlook email messages",
        "description": "Saves Outlook email messages given an account",
    },
    {
        "category": "Outlook",
        "friendly_name": "Respond to Outlook mail message",
        "description": "Responds to an Outlook message by replying or forwarding",
    },
    {
        "category": "Outlook",
        "friendly_name": "Close Outlook",
        "description": "Closes a previously launched Outlook instance",
    },
    # Excel - Advanced
    {
        "category": "Excel - Advanced",
        "friendly_name": "Resize columns/rows in Excel worksheet",
        "description": "Resizes a selection of columns or rows in the active worksheet",
    },
    {
        "category": "Excel - Advanced",
        "friendly_name": "Run Excel Macro",
        "description": "Runs a specified macro on the document of an Excel instance",
    },
    {
        "category": "Excel - Advanced",
        "friendly_name": "Get active Excel worksheet",
        "description": "Retrieves an Excel document's active worksheet",
    },
    {
        "category": "Excel - Advanced",
        "friendly_name": "Get all Excel worksheets",
        "description": "Retrieves all worksheet names of an Excel document",
    },
    {
        "category": "Excel - Advanced",
        "friendly_name": "Delete Excel worksheet",
        "description": "Deletes a specific worksheet from an Excel instance",
    },
    {
        "category": "Excel - Advanced",
        "friendly_name": "Rename Excel worksheet",
        "description": "Renames a specific worksheet of an Excel instance",
    },
    {
        "category": "Excel - Advanced",
        "friendly_name": "Activate Cell in Excel Worksheet",
        "description": "Activates a cell in the active worksheet",
    },
    {
        "category": "Excel - Advanced",
        "friendly_name": "Select cells in Excel worksheet",
        "description": "Selects a range of cells in the active worksheet",
    },
    {
        "category": "Excel - Advanced",
        "friendly_name": "Get selected cell range from Excel worksheet",
        "description": "Retrieves the selected range of cells in a structure",
    },
    {
        "category": "Excel - Advanced",
        "friendly_name": "Copy cells from Excel worksheet",
        "description": "Copies a range of cells from the active worksheet",
    },
    {
        "category": "Excel - Advanced",
        "friendly_name": "Paste cells to Excel worksheet",
        "description": "Pastes a range of cells to the active worksheet",
    },
    {
        "category": "Excel - Advanced",
        "friendly_name": "Delete from Excel worksheet",
        "description": "Deletes a cell or a range of cells from the active worksheet",
    },
    {
        "category": "Excel - Advanced",
        "friendly_name": "Insert row to Excel worksheet",
        "description": "Inserts a row above a selected row",
    },
    {
        "category": "Excel - Advanced",
        "friendly_name": "Delete row from Excel worksheet",
        "description": "Deletes a selected row from an Excel instance",
    },
    {
        "category": "Excel - Advanced",
        "friendly_name": "Insert column to Excel worksheet",
        "description": "Inserts a column to the left of a selected column",
    },
    {
        "category": "Excel - Advanced",
        "friendly_name": "Delete column from Excel worksheet",
        "description": "Deletes a selected column from an Excel instance",
    },
    {
        "category": "Excel - Advanced",
        "friendly_name": "Find and replace cells in Excel worksheet",
        "description": "Finds text and replaces it with another in the active worksheet",
    },
    {
        "category": "Excel - Advanced",
        "friendly_name": "Get first free row on column from Excel worksheet",
        "description": "Retrieves the first free row given the column",
    },
    {
        "category": "Excel - Advanced",
        "friendly_name": "Copy Excel worksheet",
        "description": "Copies a worksheet from an Excel document",
    },
    {
        "category": "Excel - Advanced",
        "friendly_name": "Read formula from Excel",
        "description": "Reads the formula inside a cell in Excel",
    },
    {
        "category": "Excel - Advanced",
        "friendly_name": "Get table range from Excel worksheet",
        "description": "Retrieves the range of a table in the active worksheet",
    },
    {
        "category": "Excel - Advanced",
        "friendly_name": "Auto fill cells in Excel worksheet",
        "description": "Auto fills a range with data based on the data of another range",
    },
    {
        "category": "Excel - Advanced",
        "friendly_name": "Append cells in Excel worksheet",
        "description": "Appends a range of cells to the active worksheet",
    },
    {
        "category": "Excel - Advanced",
        "friendly_name": "Lookup range in Excel worksheet",
        "description": "Finds and returns the result of Excel's LOOKUP function",
    },
    {
        "category": "Excel - Advanced",
        "friendly_name": "Set color of cells in Excel worksheet",
        "description": "Fills the background of the selected cells with the specified color",
    },
    # Excel
    {
        "category": "Excel",
        "friendly_name": "Launch Excel",
        "description": "Launches a new Excel instance or opens an Excel document",
    },
    {
        "category": "Excel",
        "friendly_name": "Attach to running Excel",
        "description": "Attaches to an Excel document that's already open",
    },
    {
        "category": "Excel",
        "friendly_name": "Read from Excel worksheet",
        "description": "Reads the value of a cell or a range of cells from the active worksheet",
    },
    {
        "category": "Excel",
        "friendly_name": "Get active cell on Excel worksheet",
        "description": "Gets the active cell in the active worksheet",
    },
    {
        "category": "Excel",
        "friendly_name": "Save Excel",
        "description": "Saves a previously launched Excel instance",
    },
    {
        "category": "Excel",
        "friendly_name": "Write to Excel worksheet",
        "description": "Writes a value into a cell or a range of cells",
    },
    {
        "category": "Excel",
        "friendly_name": "Close Excel",
        "description": "Closes an Excel instance",
    },
    {
        "category": "Excel",
        "friendly_name": "Set active Excel worksheet",
        "description": "Activates a specific worksheet of an Excel instance",
    },
    {
        "category": "Excel",
        "friendly_name": "Add new worksheet",
        "description": "Adds a new worksheet to the document of an Excel instance",
    },
    {
        "category": "Excel",
        "friendly_name": "Get first free column/row from Excel worksheet",
        "description": "Retrieves the first free column and/or row of the active worksheet",
    },
    {
        "category": "Excel",
        "friendly_name": "Get column name on Excel worksheet",
        "description": "Gets the name of the column",
    },
    {
        "category": "Excel",
        "friendly_name": "Clear cells in Excel worksheet",
        "description": "Clears a range of cells or a named cell in the active worksheet",
    },
    {
        "category": "Excel",
        "friendly_name": "Sort cells in Excel worksheet",
        "description": "Sorts cells in Excel worksheet",
    },
    {
        "category": "Excel",
        "friendly_name": "Sort cells based on one or more columns",
        "description": "Sorts cells based on one or more columns in an Excel worksheet",
    },
    {
        "category": "Excel",
        "friendly_name": "Filter cells in Excel worksheet",
        "description": "Applies filters on a specified column",
    },
    {
        "category": "Excel",
        "friendly_name": "Clear filters in Excel worksheet",
        "description": "Clears filters on a specified column",
    },
    {"category": "Excel", "friendly_name": "Get empty cell", "description": "Gets an empty cell"},
    # Work queues (extended)
    {
        "category": "Work queues",
        "friendly_name": "Process work queue items",
        "description": "Indicates to the orchestrator that the machine is ready to process work queue items",
    },
    {
        "category": "Work queues",
        "friendly_name": "Update work queue item",
        "description": "Updates the status and processing result of a specific work queue item",
    },
    {
        "category": "Work queues",
        "friendly_name": "Add work queue item",
        "description": "Adds a work queue item into a work queue",
    },
    {
        "category": "Work queues",
        "friendly_name": "Requeue item with delay",
        "description": "Requeues a work queue item and delays it until a specified date and time",
    },
    {
        "category": "Work queues",
        "friendly_name": "Add multiple work queue items",
        "description": "Adds one or more work queue items to a work queue",
    },
    {
        "category": "Work queues",
        "friendly_name": "Update work queue item processing notes",
        "description": "Updates the processing notes of a specific work queue item",
    },
    {
        "category": "Work queues",
        "friendly_name": "Get work queue items by filter",
        "description": "Retrieves one or more work queue items based on FetchXML filtering",
    },
    # OneDrive for Business
    {
        "category": "OneDrive for Business",
        "friendly_name": "Copy file",
        "description": "Copies a file within OneDrive",
    },
    {
        "category": "OneDrive for Business",
        "friendly_name": "Copy file using path",
        "description": "Copies a file within OneDrive by path",
    },
    {
        "category": "OneDrive for Business",
        "friendly_name": "Create file",
        "description": "Creates a file",
    },
    {
        "category": "OneDrive for Business",
        "friendly_name": "Create share link",
        "description": "Creates a share link for a file",
    },
    {
        "category": "OneDrive for Business",
        "friendly_name": "Create share link by path",
        "description": "Creates a share link for a file using the path",
    },
    {
        "category": "OneDrive for Business",
        "friendly_name": "Delete file",
        "description": "Deletes a file",
    },
    {
        "category": "OneDrive for Business",
        "friendly_name": "Extract archive to folder",
        "description": "Extracts an archive file into a folder",
    },
    {
        "category": "OneDrive for Business",
        "friendly_name": "Find files in folder",
        "description": "Finds files within a folder using search or name pattern match",
    },
    {
        "category": "OneDrive for Business",
        "friendly_name": "Find files in folder by path",
        "description": "Finds files within a folder by path",
    },
    {
        "category": "OneDrive for Business",
        "friendly_name": "Get file content",
        "description": "Gets the content of a file",
    },
    {
        "category": "OneDrive for Business",
        "friendly_name": "Get file content using path",
        "description": "Gets the content of a file using the path",
    },
    {
        "category": "OneDrive for Business",
        "friendly_name": "Get file metadata",
        "description": "Gets the metadata for a file",
    },
    {
        "category": "OneDrive for Business",
        "friendly_name": "Get file metadata using path",
        "description": "Gets the metadata of a file using the path",
    },
    {
        "category": "OneDrive for Business",
        "friendly_name": "Get file thumbnail",
        "description": "Gets the thumbnail of a file",
    },
    {
        "category": "OneDrive for Business",
        "friendly_name": "List files in folder",
        "description": "Gets the list of files and subfolders in a folder",
    },
    {
        "category": "OneDrive for Business",
        "friendly_name": "List files in root folder",
        "description": "Gets the list of files and subfolders in the root folder",
    },
    {
        "category": "OneDrive for Business",
        "friendly_name": "Move or rename a file",
        "description": "Moves or renames a file",
    },
    {
        "category": "OneDrive for Business",
        "friendly_name": "Move or rename a file using path",
        "description": "Moves or renames a file using the path",
    },
    {
        "category": "OneDrive for Business",
        "friendly_name": "Update file",
        "description": "Updates a file",
    },
    {
        "category": "OneDrive for Business",
        "friendly_name": "Upload file from URL",
        "description": "Uploads a file from a URL to OneDrive",
    },
    {
        "category": "OneDrive for Business",
        "friendly_name": "Convert file",
        "description": "Converts a file to another format",
    },
    # Excel Online (Business)
    {
        "category": "Excel Online (Business)",
        "friendly_name": "Add a key column to a table",
        "description": "Adds a key column to an Excel table",
    },
    {
        "category": "Excel Online (Business)",
        "friendly_name": "Add a row into a table",
        "description": "Adds a new row into the Excel table",
    },
    {
        "category": "Excel Online (Business)",
        "friendly_name": "Create table",
        "description": "Creates a new table in the Excel workbook",
    },
    {
        "category": "Excel Online (Business)",
        "friendly_name": "Create worksheet",
        "description": "Creates a new worksheet in the Excel workbook",
    },
    {
        "category": "Excel Online (Business)",
        "friendly_name": "Delete a row",
        "description": "Deletes a row using a key column",
    },
    {
        "category": "Excel Online (Business)",
        "friendly_name": "Get a row",
        "description": "Gets a row using a key column",
    },
    {
        "category": "Excel Online (Business)",
        "friendly_name": "Get tables",
        "description": "Gets a list of tables in the Excel workbook",
    },
    {
        "category": "Excel Online (Business)",
        "friendly_name": "Get worksheets",
        "description": "Gets a list of worksheets in the Excel workbook",
    },
    {
        "category": "Excel Online (Business)",
        "friendly_name": "List rows present in a table",
        "description": "Lists rows present in a table",
    },
    {
        "category": "Excel Online (Business)",
        "friendly_name": "Run script",
        "description": "Runs an Office Script against an Excel workbook",
    },
    {
        "category": "Excel Online (Business)",
        "friendly_name": "Run script from SharePoint library",
        "description": "Runs an Office Script from SharePoint library",
    },
    {
        "category": "Excel Online (Business)",
        "friendly_name": "Update a row",
        "description": "Updates a row using a key column",
    },
    # OneDrive
    {
        "category": "OneDrive",
        "friendly_name": "Convert file",
        "description": "Converts a file to another format",
    },
    {
        "category": "OneDrive",
        "friendly_name": "Convert file using path",
        "description": "Converts a file to another format using the path",
    },
    {
        "category": "OneDrive",
        "friendly_name": "Copy file",
        "description": "Copies a file within OneDrive",
    },
    {
        "category": "OneDrive",
        "friendly_name": "Copy file using path",
        "description": "Copies a file within OneDrive by path",
    },
    {"category": "OneDrive", "friendly_name": "Create file", "description": "Creates a file"},
    {
        "category": "OneDrive",
        "friendly_name": "Create share link",
        "description": "Creates a share link for a file",
    },
    {
        "category": "OneDrive",
        "friendly_name": "Create share link by path",
        "description": "Creates a share link for a file using the path",
    },
    {"category": "OneDrive", "friendly_name": "Delete file", "description": "Deletes a file"},
    {
        "category": "OneDrive",
        "friendly_name": "Extract archive to folder",
        "description": "Extracts an archive file into a folder",
    },
    {
        "category": "OneDrive",
        "friendly_name": "Find files in folder",
        "description": "Finds files within a folder using search or name pattern match",
    },
    {
        "category": "OneDrive",
        "friendly_name": "Find files in folder by path",
        "description": "Finds files within a folder by path using search or name pattern match",
    },
    {
        "category": "OneDrive",
        "friendly_name": "Get file content",
        "description": "Gets the content of a file",
    },
    {
        "category": "OneDrive",
        "friendly_name": "Get file content using path",
        "description": "Gets the content of a file using the path",
    },
    {
        "category": "OneDrive",
        "friendly_name": "Get file metadata",
        "description": "Gets the metadata for a file",
    },
    {
        "category": "OneDrive",
        "friendly_name": "Get file metadata using path",
        "description": "Gets the metadata of a file using the path",
    },
    {
        "category": "OneDrive",
        "friendly_name": "Get file thumbnail",
        "description": "Gets the thumbnail of a file",
    },
    {
        "category": "OneDrive",
        "friendly_name": "List files in folder",
        "description": "Gets the list of files and subfolders in a folder",
    },
    {
        "category": "OneDrive",
        "friendly_name": "List files in root folder",
        "description": "Gets the list of files and subfolders in the root folder",
    },
    {
        "category": "OneDrive",
        "friendly_name": "Move or rename a file",
        "description": "Moves or renames a file",
    },
    {
        "category": "OneDrive",
        "friendly_name": "Move or rename a file using path",
        "description": "Moves or renames a file using the path",
    },
    {"category": "OneDrive", "friendly_name": "Update file", "description": "Updates a file"},
    {
        "category": "OneDrive",
        "friendly_name": "Upload file from URL",
        "description": "Uploads a file from a URL to OneDrive",
    },
    {
        "category": "OneDrive",
        "friendly_name": "Add file tag",
        "description": "Adds a tag to a file",
    },
    {
        "category": "OneDrive",
        "friendly_name": "Get file tags",
        "description": "Gets the tags of a file",
    },
    {
        "category": "OneDrive",
        "friendly_name": "Remove file tag",
        "description": "Removes a tag from a file",
    },
    # RSS
    {
        "category": "RSS",
        "friendly_name": "List all RSS feed items",
        "description": "Retrieves all items from an RSS feed",
    },
    # Logging
    {
        "category": "Logging",
        "friendly_name": "Log Message",
        "description": "Adds a custom text message to the flow run action details",
    },
]


def extract_syntax_from_robin(robin_path: Path) -> list[tuple[str, str, str]]:
    """
    Extract PAD action calls from a .robin file.

    Looks for patterns like:
    - Module.SubModule.Action param1: val param2: val
    - Variables.SetVariable
    - External.InvokeCloudConnector
    - etc.

    Args:
        robin_path: Path to .robin or .robin.txt file

    Returns:
        List of (dotted_action_name, full_syntax_line, line_number_str)
    """
    calls = []

    try:
        with open(robin_path, encoding="utf-8", errors="ignore") as f:
            lines = f.readlines()
    except Exception as e:
        print(f"Warning: could not read {robin_path}: {e}")
        return calls

    # Pattern for action calls: Module.Submodule.Action
    # Must be followed by parameters
    action_pattern = re.compile(
        r"^\s*(?:@@)?([A-Z][a-zA-Z0-9._]*(?:\.[A-Z][a-zA-Z0-9_]*)+)\s+"
        r"([A-Za-z_][A-Za-z0-9_]*:.*)"
    )

    for line_no, line in enumerate(lines, 1):
        line = line.rstrip()

        # Skip comments and empty lines
        if not line.strip() or line.strip().startswith("#"):
            continue

        # Skip keywords that aren't action calls
        if any(
            line.strip().startswith(kw)
            for kw in [
                "SET ",
                "WAIT ",
                "IF ",
                "ELSE",
                "LOOP ",
                "BLOCK ",
                "CALL ",
                "GOTO ",
                "IMPORT ",
                "REGION",
                "ENDREGION",
                "END",
                "@@",
                "@INPUT",
                "@OUTPUT",
                "@SENSITIVE",
            ]
        ):
            continue

        # Try to match action call pattern
        match = action_pattern.search(line)
        if match:
            action_name = match.group(1)
            full_line = match.group(0).strip()

            # Filter out reserved keywords
            if action_name in ["WAIT", "SET", "IF", "LOOP", "BLOCK", "CALL", "GOTO"]:
                continue

            calls.append((action_name, full_line, f"{robin_path.name}:{line_no}"))

    return calls


def similarity(a: str, b: str) -> float:
    """Calculate string similarity 0.0-1.0."""
    return SequenceMatcher(None, a.lower(), b.lower()).ratio()


def align_pdf_to_syntax(
    pdf_actions: list[dict[str, str]], syntax_calls: dict[str, list[tuple[str, str, str]]]
) -> dict[str, ActionEntry]:
    """
    Align PDF entries to confirmed syntax via category + keyword heuristics.

    Args:
        pdf_actions: List of dicts from PDF
        syntax_calls: Dict[module_prefix -> List[(dotted_name, syntax, source)]]

    Returns:
        Dict[friendly_name -> ActionEntry] of aligned + unaligned entries
    """
    result = {}

    # Mapping of PDF categories to PAD module prefixes
    category_to_module = {
        "Variables": "Variables",
        "UI automation": "UIAutomation",
        "UI automation - Data Extraction": "UIAutomation",
        "UI automation - Form filling": "UIAutomation",
        "UI automation - Windows": "UIAutomation",
        "Excel": "Excel",
        "Work queues": "WorkQueues",
        "Office 365 Outlook": "External",
        "File management": "File",
        "Folder management": "Folder",
        "Text": "Text",
        "Date and time": "DateTime",
        "JSON": "Variables",
        "Cryptography": "Cryptography",
        "External": "External",
        "Scripting": "Scripting",
        "System": "System",
    }

    # Flatten syntax calls for easier lookup
    all_syntax_calls = []
    for calls_list in syntax_calls.values():
        all_syntax_calls.extend(calls_list)

    # Track what we've already aligned to avoid duplicates
    aligned_syntax = set()

    for pdf_action in pdf_actions:
        friendly_name = pdf_action["friendly_name"]
        category = pdf_action["category"]
        description = pdf_action["description"]

        entry = ActionEntry(
            friendly_name=friendly_name,
            category=category,
            description=description,
            confidence="description-only",
        )

        # Try to find a matching syntax call
        expected_module = category_to_module.get(category, category.split()[0])

        # Look for calls that:
        # 1. Are in the expected module/category
        # 2. Match keywords from the friendly name
        best_match = None
        best_score = 0.0

        name_keywords = set(w.lower() for w in friendly_name.split() if len(w) > 2)

        for dotted_name, syntax, source in all_syntax_calls:
            if (dotted_name, syntax, source) in aligned_syntax:
                continue

            # Check if module matches
            module_parts = dotted_name.split(".")
            module = module_parts[0] if module_parts else ""

            # Calculate match score
            score = 0.0

            # Bonus for module match
            if module.lower() == expected_module.lower():
                score += 0.4

            # Check keyword matches in method name
            method_part = ".".join(module_parts[1:]) if len(module_parts) > 1 else ""
            method_keywords = set(
                w.lower() for w in method_part.replace(".", " ").split() if len(w) > 2
            )

            common_keywords = name_keywords & method_keywords
            if common_keywords:
                keyword_ratio = len(common_keywords) / max(len(name_keywords), len(method_keywords))
                score += 0.3 + (keyword_ratio * 0.3)

            # Also check description keywords
            desc_keywords = set(w.lower() for w in description.split() if len(w) > 3)
            desc_common = method_keywords & desc_keywords
            if desc_common:
                score += 0.1

            # Overall string similarity as fallback
            sim = similarity(friendly_name, method_part.replace(".", " "))
            if sim > 0.4:
                score += sim * 0.15

            if score > best_score:
                best_score = score
                best_match = (dotted_name, syntax, source)

        # Align if we found a good match (score > threshold)
        if best_match and best_score > 0.4:
            dotted_name, syntax, source = best_match
            entry.dotted_name = dotted_name
            entry.syntax = syntax
            entry.syntax_source = source
            # CRITICAL: Only mark as "confirmed" if alignment is strong (score > 0.7)
            # Otherwise, even though we have syntax, the alignment is uncertain
            # so we must downgrade to "description-only" per Fix 2 requirement
            if best_score > 0.7:
                entry.confidence = "confirmed"
                entry.alignment = "confirmed"
            else:
                # Alignment is unconfirmed - do NOT mark syntax as confirmed
                entry.confidence = "description-only"
                entry.alignment = "unconfirmed"
                # Remove syntax fields since confidence is not "confirmed"
                entry.syntax = None
                entry.syntax_source = None
                entry.dotted_name = None
            aligned_syntax.add((dotted_name, syntax, source))

        result[friendly_name] = entry

    return result


def scan_pad_sources(src_dir: Path) -> dict[str, list[tuple[str, str, str]]]:
    """
    Scan all .robin and .txt files for action calls.

    Args:
        src_dir: Root directory to scan

    Returns:
        Dict[module_prefix -> List[(dotted_name, syntax, source_with_line)]]
    """
    result = {}

    if not src_dir.exists():
        return result

    for robin_file in src_dir.rglob("*.robin*"):
        if robin_file.name.endswith(".j2"):  # Skip Jinja templates
            continue

        calls = extract_syntax_from_robin(robin_file)
        for dotted_name, syntax, source in calls:
            module = dotted_name.split(".")[0] if "." in dotted_name else dotted_name
            if module not in result:
                result[module] = []
            result[module].append((dotted_name, syntax, source))

    # Also scan .txt files (PAD source text files)
    for txt_file in src_dir.rglob("*.txt"):
        # Skip certain files
        if any(skip in txt_file.name.lower() for skip in ["test", "temp", "tmp"]):
            continue

        calls = extract_syntax_from_robin(txt_file)
        for dotted_name, syntax, source in calls:
            module = dotted_name.split(".")[0] if "." in dotted_name else dotted_name
            if module not in result:
                result[module] = []
            result[module].append((dotted_name, syntax, source))

    return result


def main():
    """Main entry point."""
    repo_root = Path(__file__).parent.parent
    docs_dir = repo_root / "docs"
    pad_ref_dir = docs_dir / "pad-reference"

    print("PAD Action Index Builder")
    print("=" * 60)

    # Step 1: Use hardcoded PDF actions
    print("\nStep 1: Loading PDF actions...")
    pdf_actions = PDF_ACTIONS
    print(f"  Loaded {len(pdf_actions)} actions from PDF")

    # Step 2: Scan PAD source files
    print("\nStep 2: Scanning PAD source files...")
    syntax_calls = scan_pad_sources(docs_dir)
    syntax_calls_samples = scan_pad_sources(repo_root / "samples" / "pad")

    # Merge syntax calls
    for module, calls in syntax_calls_samples.items():
        if module not in syntax_calls:
            syntax_calls[module] = []
        syntax_calls[module].extend(calls)

    total_calls = sum(len(calls) for calls in syntax_calls.values())
    print(f"  Found {total_calls} action calls across {len(syntax_calls)} modules")

    # Step 3: Align PDF to syntax
    print("\nStep 3: Aligning PDF entries to confirmed syntax...")
    index = align_pdf_to_syntax(pdf_actions, syntax_calls)

    confirmed_count = sum(1 for e in index.values() if e.confidence == "confirmed")
    description_only_count = sum(1 for e in index.values() if e.confidence == "description-only")

    print(f"  Confirmed: {confirmed_count}")
    print(f"  Description-only: {description_only_count}")

    # Step 4: Build YAML output
    print(f"\nStep 4: Building YAML index ({len(index)} entries)...")

    yaml_data = {
        "_header": (
            "# PAD Action Index\n"
            "# Purpose: one entry per Power Automate Desktop action, keyed by friendly_name/description\n"
            "# for curation-time search. Complements vbo_catalogue.yaml (BP VBO runtime lookup).\n"
            "# Distinguishes confirmed (real syntax from PAD source) vs. description-only (PDF name + description,\n"
            "# no confirmed call site).\n"
            "#\n"
            "# Row format: dotted_name (if confirmed), friendly_name, category, description, confidence\n"
            '# ("confirmed" | "description-only"), syntax (only if confirmed), syntax_source (file:line, only if confirmed).\n'
            '# Never mark "confirmed" without a real syntax_source citation.\n'
            "#\n"
            "# Sources:\n"
            "# - docs/pad-reference/DF_PID_171_US_Loader.robin.txt\n"
            "# - docs/pad-reference/DF_PID_171_US_LIMS_Prelude_Main.robin.txt\n"
            "# - docs/*.robin files\n"
            "# - samples/pad/*.txt files\n"
        ),
        "actions": {},
    }

    for friendly_name in sorted(index.keys()):
        entry = index[friendly_name]
        entry_dict = asdict(entry)

        # Only include non-None fields in YAML
        clean_dict = {k: v for k, v in entry_dict.items() if v is not None}

        # Reorder keys for readability
        ordered = {}
        for key in [
            "dotted_name",
            "friendly_name",
            "category",
            "description",
            "confidence",
            "syntax",
            "syntax_source",
            "alignment",
        ]:
            if key in clean_dict:
                ordered[key] = clean_dict[key]

        yaml_data["actions"][friendly_name] = ordered

    # Step 5: Write YAML file
    output_file = pad_ref_dir / "pad-action-index.yaml"
    print(f"\nStep 5: Writing output to {output_file}...")

    # Custom YAML representer to handle the header comment
    class CustomDumper(yaml.SafeDumper):
        pass

    # Write with custom header
    with open(output_file, "w") as f:
        f.write(yaml_data["_header"])
        f.write("\n")
        del yaml_data["_header"]
        yaml.dump(
            yaml_data,
            f,
            default_flow_style=False,
            sort_keys=False,
            allow_unicode=True,
            Dumper=CustomDumper,
        )

    # Step 6: Validation
    print("\nStep 6: Validating output...")
    with open(output_file) as f:
        test_load = yaml.safe_load(f)

    if test_load and "actions" in test_load:
        action_count = len(test_load["actions"])
        confirmed = sum(
            1
            for a in test_load["actions"].values()
            if isinstance(a, dict) and a.get("confidence") == "confirmed"
        )

        # Spot-check confirmed entries have valid sources
        issues = []
        for name, action in list(test_load["actions"].items())[:5]:
            if isinstance(action, dict) and action.get("confidence") == "confirmed":
                source = action.get("syntax_source")
                if source:
                    file_part, line_part = source.rsplit(":", 1) if ":" in source else (source, "?")
                    # Try to resolve file
                    found = False
                    for search_dir in [docs_dir, repo_root / "samples" / "pad"]:
                        if (search_dir / file_part).exists():
                            found = True
                            break
                    if not found and not any(x in file_part for x in ["robin", "txt"]):
                        issues.append(f"  {name}: source file format unknown: {file_part}")

        print("\nValidation Result:")
        print(f"  Total entries: {action_count}")
        print(f"  Confirmed (real syntax): {confirmed}")
        print(f"  Description-only: {action_count - confirmed}")
        print(f"  Output file: {output_file}")

        if issues:
            print(f"\nWarnings ({len(issues)}):")
            for issue in issues:
                print(issue)

        return 0
    else:
        print("Error: YAML output is invalid")
        return 1


if __name__ == "__main__":
    exit(main())
