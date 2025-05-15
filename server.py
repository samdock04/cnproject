"""
server.py

Serves a single-player Battleship session to one connected client.
Game logic is handled entirely on the server using battleship.py.
Client sends FIRE commands, and receives game feedback.

TODO: For Tier 1, item 1, you don't need to modify this file much. 
The core issue is in how the client handles incoming messages.
However, if you want to support multiple clients (i.e. progress through further Tiers), you'll need concurrency here
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
import queue
from battleship import run_single_player_game_online, run_multi_player_round, DisconnectError

incoming = queue.Queue()
returning_players = queue.Queue()


HOST = '127.0.0.1'
PORT = 5000
global clients 
global gameOver
global connectedPlayers 
pause_clients = threading.Lock()


# Send non-game related info, e.g to keep the connection up or to inform new clients of the wait time. 
def send_server_message(player, msg):
    try:
        player["writeFile"].write(msg+"\n")
        player["writeFile"].flush()
    except Exception as e:
        print("[SERVERERROR] Could not send message.")

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
        finally: 
            still_connected = []
            for player in connectedPlayers:
                while True:
                    try:
                        send_server_message(player, "[!] The game is over. Do you want to play again? [y/n]")
                        prompt = player["readFile"].readline().strip().lower()
                        if prompt == 'y':
                            # Keep the player in the game
                            still_connected.append(player)
                            break
                        elif prompt == 'n':
                            player["connection"].close()
                            break
                        else:
                            send_server_message(player, "Please type [y/n].")
                    except:
                        print("Player is not connected as there was an error asking them to play again.")
                        #Do we have to try close the connection again?? 
                        player["connection"].close()
                        break
            # Threads keep mucking up these lists
            with pause_clients: 
                connectedPlayers.clear()
                for player in still_connected:
                    #connectedPlayers.append(player)
                    returning_players.put(player)
                    # assume someone disconnected? 
                    send_server_message(player, "Finding someone new to play a game with you!")

            break


def manage_queues():

    global connectedPlayers, clientStorage

    # continuously manage the queues and games. 

    while True: 
        print("Length of connected Players:", len(connectedPlayers), " and len of clientStorage: ", len(clientStorage))
        try: 
            player = returning_players.get_nowait()
            print("Added the returning player again!")
        except queue.Empty:
            player = incoming.get()
            print("Pulled from regular queue.")

        with pause_clients:
            # If there aren't enough players in the game. 
            if len(connectedPlayers) < 2:
                if len(clientStorage) != 0:
                    print("Someone was waiting in the queue, adding them to the game and this connection to the queue.")
                    newPlayerConnected = clientStorage.pop()
                    connectedPlayers.append(newPlayerConnected)
                    clientStorage.append(player)
                    send_server_message(newPlayerConnected, "You've been added to the game!")
                else: 
                    print("Adding this new connection to the game, no one was waiting in the queue. ")
                    connectedPlayers.append(player)

                print("After sorting, length of connected Players:", len(connectedPlayers), " and len of clientStorage: ", len(clientStorage))
                
                if len(connectedPlayers) == 2:
                    gameThread = threading.Thread(target=handle_game_clients, args=(connectedPlayers,))
                    gameThread.start()
                    print("[SERVERINFO] Game started on the server!")
                elif len(connectedPlayers) == 1:
                    send_server_message(player, "Waiting on another person to join the game...!")
                else:
                    pass
            else:
                print("[SEVERINFO] Game is in progress, adding this client to the queue. ")
                clientStorage.append(player)
                send_server_message(player, "[SERVERINFO] Thanks for joining - game in progress, you'll join when someone disconnects or a new game starts.")


def main():


    """
    We need to be able to listen for new connections, 
    sort those new connections, 
    handle the actual game. 
    ALL at the same time ???
    """

    global clientStorage 
    global connectedPlayers
    connectedPlayers = []
    # for waiting players
    clientStorage = []
    clients = 0
    
    print(f"[INFO] Server listening on {HOST}:{PORT}")
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
        s.bind((HOST, PORT))
        s.listen(2)
        print("[SERVERINFO] Listening for clients, waiting for at least 2 to start game...")
        started = False
    
        # Each conn should be unique?? So we can store them here? 
        storeConns = []
        # Don't start the game until we at least have 2
        manage_queue_thread = threading.Thread(target=manage_queues)
        manage_queue_thread.start()

        while True: 

            print("[SERVERINFO] Main thread is listening for new connections!")
            # Listen for a new incoming request
            conn, addr = s.accept()

            print(f"[SERVERINFO] Connection received from {addr}")

             # Form a new player for the connection 
            player = {
                "connection": conn,
                "readFile": conn.makefile('r'),
                "writeFile": conn.makefile('w'),
            }

            with pause_clients:
                incoming.put(player)
            # I needed to add all of this to a separate thread, as we were getting stuck waiting for a new connection before proceeding to 
            # shuffle the queues when a new game started. 
        
if __name__ == "__main__":
    main()
