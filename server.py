"""
server.py

Serves a single-player Battleship session to one connected client.
Game logic is handled entirely on the server using battleship.py.
Client sends FIRE commands, and receives game feedback.

TODO: For Tier 1, item 1, you don't need to modify this file much. 
The core issue is in how the client handles incoming messages.
However, if you want to support multiple clients (i.e. progress through further Tiers), you'll need concurrency here too.
"""

import socket
import threading
from battleship import run_single_player_game_online, run_multi_player_round, DisconnectError


HOST = '127.0.0.1'
PORT = 5000
global clients 
global gameOver
global connectedPlayers 


# Send non-game related info, e.g to keep the connection up or to inform new clients of the wait time. 
def send_server_message(player, msg):
    player["writeFile"].write(msg+"\n")
    player["writeFile"].flush()

def handle_game_clients(connectedPlayers):
    global clients
    global gameOver
    # Get the queue of people waiting to play. 
    global clientStorage

    while True:
        try:
            print("[INFO] A game has started on this server!")
            run_multi_player_round(connectedPlayers[0], connectedPlayers[1])
        except Exception as e:
            print("Someone disconnected. Prompting both users to see who it was. ")
            for player in connectedPlayers:
                while True:
                    try:
                        send_server_message("[!] The game is over. Do you want to play again? [y/n]", player)
                        prompt = player["readFile"].readline().strip().lower()
                        if prompt == 'y':
                                # Keep the player in the game
                            break
                        elif prompt == 'n':
                            connectedPlayers.remove(player)
                            break
                        else:
                            send_server_message("Please type [y/n]. ")
                    except:
                        print("Player is not connected as there was an error asking them to play again.")
                        connectedPlayers.remove(player)
                        break
            break


def main():

    playAgain = 0 
    global clientStorage 
    global clients
    global connectedPlayers
    connectedPlayers = []
    clients = 0
    
    print(f"[INFO] Server listening on {HOST}:{PORT}")
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
        s.bind((HOST, PORT))
        s.listen(2)
        print("[SERVERINFO] Listening for clients, waiting for at least 2 to start game...")
    
        # Each conn should be unique?? So we can store them here? 
        storeConns = []
        # Don't start the game until we at least have 
        while True: 

            print("[SERVERINFO] Main thread is still listening for new connections.")
            # Listen for a new incoming request
            conn, addr = s.accept()

            print(f"[SERVERINFO] Connection received from {addr}")

             # Form a new player for the connection 
            player = {
                "connection": conn,
                "readFile": conn.makefile('r'),
                "writeFile": conn.makefile('w'),
            }

            clients+=1

            if clients < 2:
                connectedPlayers.append(player)
            # If there are two clients, start the game. 
            elif clients == 2: 
                connectedPlayers.append(player)
                gameThread = threading.Thread(target=handle_game_clients, args=(connectedPlayers,))
                gameThread.start()
                print("[SERVERINFO] Still waiting on another player to join.")
            elif clients > 2:
                print("[SERVERINFO] A game is probably already in progress, queue this client.")
                #queue this player 
                clientStorage.append(player)



# HINT: For multiple clients, you'd need to:
# 1. Accept connections in a loop
# 2. Handle each client in a separate thread
# 3. Import threading and create a handle_client function

if __name__ == "__main__":
    main()