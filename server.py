import socket
import threading
import queue
import time
from battleship import run_single_player_game_online, run_multi_player_round, DisconnectError
from shared import last_move_time, gameOverPrompt

incoming = queue.Queue()
returning_players = queue.Queue()


HOST = '127.0.0.1'
PORT = 5002
global clients 
global gameOver
global connectedPlayers 
global clientStorage
global recentDisconnect
global newGame
global gameStateOne
global gameStateTwo
pause_clients = threading.Lock()

TIMEOUT_SECS = 30

timeout_forfeit_occurred = threading.Event()


# Send non-game related info, e.g to keep the connection up or to inform new clients of the wait time. 
def send_server_message(player, msg):
    try:
        player["writeFile"].write(msg+"\n")
        player["writeFile"].flush()
    except Exception as e:
        print("[SERVERERROR] Could not send message.")

def send_all_message(msg):
    print(msg)
    for client in connectedPlayers:
        try:
            client["writeFile"].write(msg+"\n")
            client["writeFile"].flush()
        except:
            pass
    for client in clientStorage:
        try:
            client["writeFile"].write(msg+'\n')
            client["writeFile"].flush()
        except:
            pass


def prompt_replay(player, result_queue):
    try:
        # set a timeout for the socket
        player["connection"].settimeout(10)
        while True:
            player["writeFile"].write("[!] The game is over. Do you want to play again? [y/n]\n")
            player["writeFile"].flush()
            try:
                response = player["readFile"].readline()
            except socket.timeout:
                print(f"[REPLAY] Player {player['connection']} did not respond in time. Disconnecting")
                result_queue.put((player, 'n'))
                try:
                    player["connection"].shutdown(socket.SHUT_RDWR)
                    player["connection"].close()
                except:
                    pass
            if not response:
                print(f"[REPLAY] No response from player {player['connection']}. Assuming 'n'.")
                result_queue.put((player, 'n'))
                return
            response = response.strip().lower()
            print(f"[REPLAY] Player {player['connection']} answered: {response}")
            if response in ('y', 'n'):
                result_queue.put((player, response))
                print("input received.")
                return
            else:
                player["writeFile"].write("Invalid input. Please type 'y' or 'n'.\n")
                player["writeFile"].flush()
    except Exception as e:
        print(f"[SERVERINFO] Error while prompting replay: {e}")
        result_queue.put((player, 'n'))
    finally:
        # remove timeout so doesn't affect other reads
        try:
            player["connection"].settimeout(None)
        except:
            pass

def handle_game_clients(connectedPlayers):
    global clients
    global gameOver
    # Get the queue of people waiting to play. 
    global clientStorage
    global recentDisconnect
    global newGame
    global gameStateOne
    global gameStateTwo

    for client in connectedPlayers:
        last_move_time[client["connection"]] = 0

    gameOverPrompt[0] = False
    
    def monitor_timeout(player, opponent):

        while last_move_time[player["connection"]] == 0:
            time.sleep(0.5)

        while True:
            time.sleep(1)
            if gameOverPrompt[0]:
                break
            if time.time() - last_move_time[player["connection"]] > TIMEOUT_SECS:
                try:
                    player["writeFile"].write("[!] Timeout! You have forfeited. Disconnecting...\n")
                    player["writeFile"].flush()

                    opponent["writeFile"].write("[!] Opponent has forfeited due to inactivity. You win!!\n")
                    opponent["writeFile"].flush()

                    send_all_message(f"The current game has ended: {opponent['username']} won ({player['username']} disconnected).")


                except:
                    pass

                print(f"[SERVERINFO] Timeout for {player['connection']}. Forfeit...prompting.")
                gameOverPrompt[0] = True
                timeout_forfeit_occurred.set()
                break

    t1 = threading.Thread(target=monitor_timeout, args=(connectedPlayers[0], connectedPlayers[1]))
    t1.start()
    while True: 
        try:
            if newGame:
                #print("[INFO] A new game has started on this server!")
                start_msg = f"A new game has started between {connectedPlayers[0]['username']} and {connectedPlayers[1]['username']}!"
                send_all_message(start_msg)
                gameStateOne, gameStateTwo = run_multi_player_round(connectedPlayers[0], connectedPlayers[1], clientStorage, newGame, False, False)
            else:
                print("[INFO] A game has resumed on this server!")
                gameStateOne, gameStateTwo = run_multi_player_round(connectedPlayers[0], connectedPlayers[1], clientStorage, newGame, gameStateOne, gameStateTwo)
        except Exception as e:
            print(f"[SERVERERROR] Error in game thread: {e}")
            print("Someone disconnected. Prompting both users to see who it was. ")
        finally: 
            still_connected = []
            toRemove = []

            if timeout_forfeit_occurred.is_set():
                print("[SERVERINFO] Timeout forfeit occurred. Skipping reconnection wait")
                timeout_forfeit_occurred.clear()
                still_connected = connectedPlayers[:]

                result_queue = queue.Queue()
                threads = []

                for player in still_connected:
                    t = threading.Thread(target=prompt_replay, args=(player, result_queue))
                    t.start()
                    threads.append(t)

                for t in threads:
                   t.join()

                with pause_clients:
                    connectedPlayers.clear()
                    while not result_queue.empty():
                        player, response = result_queue.get()
                        if response == 'y':
                            clientStorage.append(player)
                            send_server_message(player, "[SERVERINFO] You've been added back to the queue.")
                        else:
                            try:
                                player["connection"].shutdown(socket.SHUT_RDWR)
                                player["connection"].close()
                            except:
                                pass
                    
                    print("Length of connected Players:", len(connectedPlayers), " and len of clientStorage: ", len(clientStorage))
                    # If both current players don't want to replay ('n') and someone was waiting
                    if len(clientStorage) == 1 and len(connectedPlayers) == 0:
                        print("Someone was waiting in the queue, adding them to the game...")
                        waiting_player = clientStorage.pop(0)
                        connectedPlayers.append(waiting_player)
                        print(f"[SERVERINFO] Added player: {waiting_player['username']}")
                        send_server_message(waiting_player, "You've been added to the game!")
                        send_server_message(waiting_player, "Waiting for another player to join the game...")

                    # If both current players don't want to replay, and the queue has more than 2 ppl waiting
                    elif len(clientStorage) >= 2:
                        player1 = clientStorage.pop(0)
                        player2 = clientStorage.pop(0)
                        connectedPlayers.extend([player1, player2])
                        timeout_forfeit_occurred.clear()
                        print("[SERVERINFO] Starting next match with new players.")
                        gameThread = threading.Thread(target=handle_game_clients, args=(connectedPlayers,))
                        gameThread.start()
                    
                    # If both current players don't want to replay, and no one is in queue
                    elif len(clientStorage) == 0 and len(connectedPlayers) == 0:
                        print("[SERVERINFO] ")


                return
            
            else:
                #    Check who we can send messages to, to figure out who is still connected. 
                for player in connectedPlayers:
                    try:
                        player["writeFile"].write("[!] A client disconnected, waiting for them to rejoin...\n")
                        player["writeFile"].flush()
                    except Exception as e:
                        print("[SERVERERROR] Could not send message to player.")
                        try:
                            recentDisconnect = player["username"]
                            player["connection"].close()
                            toRemove.append(player)
                        except:
                            pass
            for player in toRemove:
                connectedPlayers.remove(player)
            # Give them a chance to rejoin... 
            time.sleep(10)
            print("The len of connected players is: ", len(connectedPlayers))
            # We update connectedPlayers during this time in the main thread...
            recentDisconnect = None
            if len(connectedPlayers) == 1:
                # Prompt both players to see if they want to play again.
                for player in connectedPlayers:
                    while True:
                        try:
                            player["writeFile"].write("[!] The game is over. Do you want to play again? [y/n]\n")
                            player["writeFile"].flush()
                            prompt = player["readFile"].readline()
                            if not prompt:
                                raise ConnectionError("Player disconnected")
                            prompt = prompt.strip().lower()
                            if prompt == 'y':                                
                                clientStorage.append(player)
                                send_server_message(player, "[SERVERINFO] You've been added back to the queue.")
                                break
                            elif prompt == 'n':
                                player["connection"].shutdown( socket.SHUT_RDWR)
                                player["connection"].close()
                                break
                            else:
                                player["writeFile"].write("Please type [y/n].\n")
                                player["writeFile"].flush()
                        except Exception as e:
                            print("[SERVERINFO] Could not prompt player — assumed disconnected.")
                            try:
                                player["connection"].close()
                            except:
                                pass
                            break
                
                # Threads keep mucking up these lists
                with pause_clients: 
                    connectedPlayers.clear()
                    for player in still_connected:
                        connectedPlayers.append(player)
                        returning_players.put(player)
                        # assume someone disconnected? 
                        send_server_message(player, "Finding someone new to play a game with you!")

                    if len(connectedPlayers) == 0 and len(clientStorage) >= 2:
                        player1 = clientStorage.pop(0)
                        player2 = clientStorage.pop(0)
                        connectedPlayers.extend([player1, player2])
                        timeout_forfeit_occurred.clear()
                        print("[SERVERINFO] Starting next match with new players.")
                        gameThread = threading.Thread(target=handle_game_clients, args=(connectedPlayers,))
                        gameThread.start()

                    else:
                        
                        #print("Length of connected Players:", len(connectedPlayers), " and len of clientStorage: ", len(clientStorage))
                        while len(connectedPlayers) < 2 and len(clientStorage) > 0:
                            newPlayerConnected = clientStorage.pop(0)
                            connectedPlayers.append(newPlayerConnected)
                            send_server_message(newPlayerConnected, "You've been added to the game!")
                        if len(connectedPlayers) == 2:
                            gameThread = threading.Thread(target=handle_game_clients, args=(connectedPlayers,))
                            gameThread.start()
                            print("[SERVERINFO] Game started on the server!")

                break

            # The player reconnected in this time, we added it straight to connectedPlayers. 
            elif len(connectedPlayers) == 2:
                newGame = False
                print("Starting a new game with the same players, this should pick up from the last game.")
                gameThread = threading.Thread(target=handle_game_clients, args=(connectedPlayers,))
                gameThread.start()
            break





def manage_queues():

    global connectedPlayers, clientStorage, recentDisconnect, newGame


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

            #while len(connectedPlayers) < 2 and len(clientStorage) > 0:
            #    newPlayerConnected = clientStorage.pop(0)
            #    connectedPlayers.append(newPlayerConnected)
            #    send_server_message(newPlayerConnected, "You've been added to the game!")
            # If there aren't enough players in the game. 
            if len(connectedPlayers) < 2:
                if len(clientStorage) != 0:
                    print("Someone was waiting in the queue, adding them to the game and this connection to the queue.")
                    newPlayerConnected = clientStorage.pop(0)
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
                if not any(p["username"] == player["username"] for p in connectedPlayers):
                    print("[SERVERINFO] Game is in progress, adding this client to the queue. ")
                    clientStorage.append(player)
                    send_server_message(player, f"[SERVERINFO] Thanks for joining - game in progress between {connectedPlayers[0]['username']} and {connectedPlayers[1]['username']}, you'll join when someone disconnects or a new game starts. You can be a spectator for now!")



def handle_new_connection(conn, addr):
    global connectedPlayers, clientStorage, recentDisconnect, newGame
    #global gameStateOne, gameStateTwo

    print(f"[SERVERINFO] New connection from {addr}")
    writeFile = conn.makefile('w')
    readFile = conn.makefile('r')
    writeFile.write(f"Enter your username: \n")
    writeFile.flush()
    username = readFile.readline().strip()
    writeFile.write(f"Hello {username}, welcome to the game!\n")
    writeFile.flush()
    player = {
     "connection": conn,
     "readFile": conn.makefile('r'),
     "writeFile": conn.makefile('w'),
     "username": username
    }
    """
    # need logic for restoring the gameState's
    # encountering: [SERVERERROR] Error in game thread: 'board'
    if username == gameStateOne.get("username", ""):
        for key in ["board", "opponentBoard", "shots"]:
            if key in gameStateOne:
                player[key] = gameStateOne[key]
    elif username == gameStateTwo.get("username", ""):
        for key in ["board", "opponentBoard", "shots"]:
            if key in gameStateTwo:
                player[key] = gameStateTwo[key]

    """

    with pause_clients:
        if player["username"] == recentDisconnect:
            connectedPlayers.append(player)
            print("Added the returning player again!")
            newGame = False
        else:
            newGame = True
            incoming.put(player)

def main():


    """
    We need to be able to listen for new connections, 
    sort those new connections, 
    handle the actual game. 
    ALL at the same time ???
    """

    global clientStorage 
    global connectedPlayers
    global recentDisconnect
    recentDisconnect = None
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

            handle_conn_thread = threading.Thread(target=handle_new_connection, args=(conn, addr,))
            handle_conn_thread.start()
            # I needed to add all of this to a separate thread, as we were getting stuck waiting for a new connection before proceeding to 
            # shuffle the queues when a new game started. 
        
if __name__ == "__main__":
    main()
