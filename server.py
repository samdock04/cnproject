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
pause_clients = threading.Lock()

TIMEOUT_SECS = 10


# Send non-game related info, e.g to keep the connection up or to inform new clients of the wait time. 
def send_server_message(player, msg):
    try:
        player["writeFile"].write(msg+"\n")
        player["writeFile"].flush()
    except Exception as e:
        print("[SERVERERROR] Could not send message.")

def prompt_replay(player, result_queue):
    try:
        while True:
            player["writeFile"].write("[!] The game is over. Do you want to play again? [y/n]\n")
            player["writeFile"].flush()
            response = player["readFile"].readline()
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

def handle_game_clients(connectedPlayers):
    global clients
    global gameOver
    # Get the queue of people waiting to play. 
    global clientStorage

    for client in connectedPlayers:
        last_move_time[client["connection"]] = time.time()

    gameOverPrompt[0] = False
    
    def monitor_timeout(player, opponent):
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
                except:
                    pass

                print(f"[SERVERINFO] Timeout for {player['connection']}. Forfeit...prompting.")
                gameOverPrompt[0] = True
                break


                """
                try:
                    player["connection"].close()
                except:
                    pass
                try:
                    opponent["connection"].close()
                except:
                    pass
                print(f"[SERVERINFO] Timeout for {client['connection']}. Forfeit...disconnecting.")
                break
                """

    t1 = threading.Thread(target=monitor_timeout, args=(connectedPlayers[0], connectedPlayers[1]))
    t1.start()

    try:
        print("[INFO] A game has started on this server!")
        run_multi_player_round(connectedPlayers[0], connectedPlayers[1])
    except Exception as e:
        print("Someone disconnected. Prompting both users to see who it was. ")
    finally: 
        result_queue = queue.Queue()
        threads = []

        for player in connectedPlayers:
            t = threading.Thread(target=prompt_replay, args=(player, result_queue))
            t.start()
            threads.append(t)

        #for t in threads:
            #t.join()

        still_connected = []
        responses_received = 0

        #while not result_queue.empty():
        while responses_received < len(connectedPlayers):
            player, response = result_queue.get()
            responses_received += 1

            print(f"[SERVERINFO] Received response: {response} from {player['connection']}")

            if response == 'y':
                still_connected.append(player)
                send_server_message(player, "[SERVERINFO] You've been added back to the queue.")
            else:
                try:
                    send_server_message(player, "[SERVERINFO] You are being disconnected.")
                    print(f"Disconnecting player: {player['connection']}")
                    player["writeFile"].flush()
                    time.sleep(0.1)
                    print(response)
                    player["connection"].shutdown(socket.SHUT_RDWR)
                    player["connection"].close()
                except:
                    pass

        with pause_clients:
            connectedPlayers.clear()
            for player in still_connected:
                returning_players.put(player)
                send_server_message(player, "Added you back to the queue. Waiting for someone else to play with you!!!!.")
                send_server_message(player, "Finding someone new to play a game with you!")

        print("[SERVERINFO] Game thread ended. Waiting for new players...")


def manage_queues():

    global connectedPlayers, clientStorage

    # continuously manage the queues and games. 

    while True: 
        print("Length of connected Players:", len(connectedPlayers), " and len of clientStorage: ", len(clientStorage))
        try: 
            player = returning_players.get_nowait()
            print("Added the returning player again!")
        except queue.Empty:
            try:
                player = incoming.get_nowait()
            except queue.Empty:
                time.sleep(0.2)
                continue


        with pause_clients:
            # If there aren't enough players in the game. 
            if len(connectedPlayers) < 2:
                if len(clientStorage) != 0:
                    print("Someone was waiting in the queue, adding them to the game and this connection to the queue.")
                    newPlayerConnected = clientStorage.pop(0) # queue data structure instead of stack
                    connectedPlayers.append(newPlayerConnected)
                    connectedPlayers.append(player)
                    #clientStorage.append(player)
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
