"""
client.py

Connects to a Battleship server which runs the single-player game.
Simply pipes user input to the server, and prints all server responses.

TODO: Fix the message synchronization issue using concurrency (Tier 1, item 1).
"""

import socket
import threading
import time

HOST = '127.0.0.1'
PORT = 5000

# HINT: The current problem is that the client is reading from the socket,
# then waiting for user input, then reading again. This causes server
# messages to appear out of order.
#
# Consider using Python's threading module to separate the concerns:
# - One thread continuously reads from the socket and displays messages
# - The main thread handles user input and sends it to the server
#
# import threading



stopInput = threading.Event()
# placeholder variable to notify the main thread when we try to exit
exited = 0 

def main():

    global exited

    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
        s.connect((HOST, PORT))
        rfile = s.makefile('r')
        wfile = s.makefile('w')

        t1 = threading.Thread(target=receive_messages, args=(rfile,))
        t1.start()

        try:

                # use the threading event to stop input from being allowed until we receive something. 
           
            while not exited: 
                #print("Exited is currently", str(exited))
                stopInput.wait()
                user_input = input("Your turn >>")
                wfile.write(user_input + '\n')
                #print("Input ended!")
                wfile.flush()
                #print("Sent this input!")
                # Clear it, block input again 
                stopInput.clear()

            s.shutdown(socket.SHUT_RDWR) 
            s.close()
            t1.join()
            exit()


        except KeyboardInterrupt:
            print("\n[INFO] Client exiting.")
            s.shutdown(socket.SHUT_RDWR) 
            s.close()
            t1.join()
            exit()

# HINT: A better approach would be something like:

def receive_messages(rfile):

    global exited
#     """Continuously receive and display messages from the server"""
    try:
        while True:
            line = rfile.readline()
            if not line:
                print("[INFO] Server disconnected.")
                break
            elif "Enter" in line:
                # open input as the server has prompted you to enter. 
                stopInput.set()
            # Allow input if the server is giving you another turn after incorrect input. 
            elif "Invalid input" in line:
                stopInput.set()
            # if the server is responding to 'quit', or if the server disconnected. 
            elif "Thanks for playing" in line or "Server disconnected" in line: 
                print("[CLIENT INFO] You've left the game.")
                exited = 1
            elif "play again" in line: 
                stopInput.set()

            print(line.strip())

            # Open up input as we've received something. 
    except Exception as e:
        #print(f"Exiting! Either you've typed quit or pressed the keyboard shortcut to quit.")
        pass

if __name__ == "__main__":
    main()
