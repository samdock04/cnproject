"""
battleship.py

Contains core data structures and logic for Battleship, including:
 - Board class for storing ship positions, hits, misses
 - Utility function parse_coordinate for translating e.g. 'B5' -> (row, col)
 - A test harness run_single_player_game() to demonstrate the logic in a local, single-player mode

"""

import random
from shared import last_move_time, gameOverPrompt
import socket
import threading
import queue
import time
import select
from collections import Counter

BOARD_SIZE = 10
SHIPS = [
    ("CARRIER", 5),
    ("BATTLESHIP", 4)
]

"""
SHIPS = [
    ("CARRIER", 5),
    ("BATTLESHIP", 4),
    ("CRUISER", 3),
    ("SUBMARINE", 3),
    ("DESTROYER", 2)
]
"""


class DisconnectError(Exception):
    "Raised exception to deal with disconnected user."
    pass


class Board:
    """
    Represents a single Battleship board with hidden ships.
    We store:
      - self.hidden_grid: tracks real positions of ships ('S'), hits ('X'), misses ('o')
      - self.display_grid: the version we show to the player ('.' for unknown, 'X' for hits, 'o' for misses)
      - self.placed_ships: a list of dicts, each dict with:
          {
             'name': <ship_name>,
             'positions': set of (r, c),
          }
        used to determine when a specific ship has been fully sunk.

    In a full 2-player networked game:
      - Each player has their own Board instance.
      - When a player fires at their opponent, the server calls
        opponent_board.fire_at(...) and sends back the result.
    """

    def __init__(self, size=BOARD_SIZE):
        self.size = size
        # '.' for empty water
        self.hidden_grid = [['.' for _ in range(size)] for _ in range(size)]
        # display_grid is what the player or an observer sees (no 'S')
        self.display_grid = [['.' for _ in range(size)] for _ in range(size)]
        self.placed_ships = []  # e.g. [{'name': 'Destroyer', 'positions': {(r, c), ...}}, ...]

    def place_ships_randomly(self, ships=SHIPS):
        """
        Randomly place each ship in 'ships' on the hidden_grid, storing positions for each ship.
        In a networked version, you might parse explicit placements from a player's commands
        (e.g. "PLACE A1 H BATTLESHIP") or prompt the user for board coordinates and placement orientations; 
        the self.place_ships_manually() can be used as a guide.
        """
        for ship_name, ship_size in ships:
            placed = False
            while not placed:
                orientation = random.randint(0, 1)  # 0 => horizontal, 1 => vertical
                row = random.randint(0, self.size - 1)
                col = random.randint(0, self.size - 1)

                if self.can_place_ship(row, col, ship_size, orientation):
                    occupied_positions = self.do_place_ship(row, col, ship_size, orientation)
                    self.placed_ships.append({
                        'name': ship_name,
                        'positions': occupied_positions
                    })
                    placed = True


    def place_ships_manually(self, ships=SHIPS):
        """
        Prompt the user for each ship's starting coordinate and orientation (H or V).
        Validates the placement; if invalid, re-prompts.
        """
        print("\nPlease place your ships manually on the board.")
        for ship_name, ship_size in ships:
            while True:
                self.print_display_grid(show_hidden_board=True)
                print(f"\nPlacing your {ship_name} (size {ship_size}).")
                coord_str = input("  Enter starting coordinate (e.g. A1): ").strip()
                orientation_str = input("  Orientation? Enter 'H' (horizontal) or 'V' (vertical): ").strip().upper()

                try:
                    row, col = parse_coordinate(coord_str)
                except ValueError as e:
                    print(f"  [!] Invalid coordinate: {e}")
                    continue

                # Convert orientation_str to 0 (horizontal) or 1 (vertical)
                if orientation_str == 'H':
                    orientation = 0
                elif orientation_str == 'V':
                    orientation = 1
                else:
                    print("  [!] Invalid orientation. Please enter 'H' or 'V'.")
                    continue

                # Check if we can place the ship
                if self.can_place_ship(row, col, ship_size, orientation):
                    occupied_positions = self.do_place_ship(row, col, ship_size, orientation)
                    self.placed_ships.append({
                        'name': ship_name,
                        'positions': occupied_positions
                    })
                    break
                else:
                    print(f"  [!] Cannot place {ship_name} at {coord_str} (orientation={orientation_str}). Try again.")


    def can_place_ship(self, row, col, ship_size, orientation):
        """
        Check if we can place a ship of length 'ship_size' at (row, col)
        with the given orientation (0 => horizontal, 1 => vertical).
        Returns True if the space is free, False otherwise.
        """
        if orientation == 0:  # Horizontal
            if col + ship_size > self.size:
                return False
            for c in range(col, col + ship_size):
                if self.hidden_grid[row][c] != '.':
                    return False
        else:  # Vertical
            if row + ship_size > self.size:
                return False
            for r in range(row, row + ship_size):
                if self.hidden_grid[r][col] != '.':
                    return False
        return True

    def do_place_ship(self, row, col, ship_size, orientation):
        """
        Place the ship on hidden_grid by marking 'S', and return the set of occupied positions.
        """
        occupied = set()
        if orientation == 0:  # Horizontal
            for c in range(col, col + ship_size):
                self.hidden_grid[row][c] = 'S'
                occupied.add((row, c))
        else:  # Vertical
            for r in range(row, row + ship_size):
                self.hidden_grid[r][col] = 'S'
                occupied.add((r, col))
        return occupied

    def fire_at(self, row, col):
        """
        Fire at (row, col). Return a tuple (result, sunk_ship_name).
        Possible outcomes:
          - ('hit', None)          if it's a hit but not sunk
          - ('hit', <ship_name>)   if that shot causes the entire ship to sink
          - ('miss', None)         if no ship was there
          - ('already_shot', None) if that cell was already revealed as 'X' or 'o'

        The server can use this result to inform the firing player.
        """
        cell = self.hidden_grid[row][col]
        if cell == 'S':
            # Mark a hit
            self.hidden_grid[row][col] = 'X'
            self.display_grid[row][col] = 'X'
            # Check if that hit sank a ship
            sunk_ship_name = self._mark_hit_and_check_sunk(row, col)
            if sunk_ship_name:
                return ('hit', sunk_ship_name)  # A ship has just been sunk
            else:
                return ('hit', None)
        elif cell == '.':
            # Mark a miss
            self.hidden_grid[row][col] = 'o'
            self.display_grid[row][col] = 'o'
            return ('miss', None)
        elif cell == 'X' or cell == 'o':
            return ('already_shot', None)
        else:
            # In principle, this branch shouldn't happen if 'S', '.', 'X', 'o' are all possibilities
            return ('already_shot', None)

    def _mark_hit_and_check_sunk(self, row, col):
        """
        Remove (row, col) from the relevant ship's positions.
        If that ship's positions become empty, return the ship name (it's sunk).
        Otherwise return None.
        """
        for ship in self.placed_ships:
            if (row, col) in ship['positions']:
                ship['positions'].remove((row, col))
                if len(ship['positions']) == 0:
                    return ship['name']
                break
        return None

    def all_ships_sunk(self):
        """
        Check if all ships are sunk (i.e. every ship's positions are empty).
        """
        for ship in self.placed_ships:
            if len(ship['positions']) > 0:
                return False
        return True

    def print_display_grid(self, show_hidden_board=False):
        """
        Print the board as a 2D grid.
        
        If show_hidden_board is False (default), it prints the 'attacker' or 'observer' view:
        - '.' for unknown cells,
        - 'X' for known hits,
        - 'o' for known misses.
        
        If show_hidden_board is True, it prints the entire hidden grid:
        - 'S' for ships,
        - 'X' for hits,
        - 'o' for misses,
        - '.' for empty water.
        """
        # Decide which grid to print
        grid_to_print = self.hidden_grid if show_hidden_board else self.display_grid

        # Column headers (1 .. N)
        print("  " + "".join(str(i + 1).rjust(2) for i in range(self.size)))
        # Each row labeled with A, B, C, ...
        for r in range(self.size):
            row_label = chr(ord('A') + r)
            row_str = " ".join(grid_to_print[r][c] for c in range(self.size))
            print(f"{row_label:2} {row_str}")

    def get_display_string(self, show_hidden_board=False):
        result = "  " + " ".join(str(i+1) for i in range(BOARD_SIZE)) + "\n"
        for i in range(BOARD_SIZE):
            row = chr(ord('A') + i)
            result += row + " "
            for j in range(BOARD_SIZE):
                cell = self.display_grid[i][j]
                if cell == " ":
                    result += ". "
                elif cell == "X":
                    result += "X "
                elif cell == "O":
                    result += "O "
                else:
                    result += (cell + " ") if show_hidden_board else ". "
            result += "\n"
        return result


def parse_coordinate(coord_str):
    """
    Convert something like 'B5' into zero-based (row, col).
    Example: 'A1' => (0, 0), 'C10' => (2, 9)
    HINT: you might want to add additional input validation here...
    """
    coord_str = coord_str.strip().upper()
    row_letter = coord_str[0]
    col_digits = coord_str[1:]

    if row_letter > 'J': 
        print("Row is out of the range; should be A-J")
    elif not row_letter.isalpha():
        print("Invalid, try enter a letter and a number as the coordinate, e.g B5.")
        raise IndexError 

    if not 0 < int(col_digits) <= 10: 
        print("Column is out of range, should be 1-10.")
    print("We'll proceed.")

    row = ord(row_letter) - ord('A')
    col = int(col_digits) - 1  # zero-based

    return (row, col)

# added for multiplayer ship placement
def network_place_ships(board, readFile, writeFile):
    
    send("\nPlace your ships one-by-one. Format: PLACE A1 H Destroyer", writeFile)
    send("[SERVERINFO] Example board layout below:", writeFile)
    send("  " + " ".join(str(i+1) for i in range(BOARD_SIZE)), writeFile)
    for i in range(BOARD_SIZE):
        row_label = chr(ord('A') + i)
        send(row_label + " " + ". " * BOARD_SIZE, writeFile)

    ship_targets = Counter(s[0] for s in SHIPS)

    # Track how many of each have been placed
    ship_placed = Counter()

    available = ', '.join([s[0] for s in SHIPS])
    send(f"Available ships: {available}", writeFile)
    #placed_ships = set()

    while sum(ship_placed.values()) < len(SHIPS):
        send(f"\n[SERVERINFO] Ships placed so far:", writeFile)
        for ship in ship_targets:
            placed = ship_placed.get(ship, 0)
            total = ship_targets[ship]
            send(f"  - {ship}: {placed} of {total}", writeFile)
        send("Enter placement command:", writeFile)
        msg = recv(readFile).strip()

        try:
            if not msg.startswith("PLACE"):
                send("Invalid format. Use: PLACE A1 H DESTROYER", writeFile)
                continue

            _, coord, orient, shipname = msg.split()
            shipname = shipname.upper()
            row, col = parse_coordinate(coord.upper())
            orientation = 0 if orient.upper() == 'H' else 1 if orient.upper() == 'V' else None

            if shipname not in [s[0] for s in SHIPS]:
                send(f"Unknown ship name. '{shipname}'. Available: {', '.join([s[0] for s in SHIPS])}", writeFile)
                continue

            if ship_placed[shipname] >= ship_targets[shipname]:
                send(f"All {shipname} ships already placed.", writeFile)
                continue

            #if shipname in placed_ships:
                #send("That ship is already placed.", writeFile)
                #continue

            

            ship = next(s for s in SHIPS if s[0] == shipname)
            if board.can_place_ship(row, col, ship[1], orientation):
                positions = board.do_place_ship(row, col, ship[1], orientation)
                board.placed_ships.append({"name": ship[0], "positions": positions})
                #placed_ships.add(shipname)
                ship_placed[shipname] += 1
                orientation_full = "horizontally" if orientation == 0 else "vertically"
                send(f"{shipname.capitalize()} placed at {coord.upper()} {orientation_full}.", writeFile)
                remaining = ship_targets[shipname] - ship_placed[shipname]
                send(f"[SERVERINFO] {ship_placed[shipname]} of {ship_targets[shipname]} {shipname}(s) placed. Remaining: {remaining}", writeFile)
            else:
                send("Invalid position. Try again.", writeFile)

        except Exception as e:
            send(f"Error: {e}", writeFile)

    return board

# for multiplayer ship placement
def send(message, writeFile):
    writeFile.write(message + "\n")
    writeFile.flush()

# for multiplayer ship placement
def recv(readFile):
    return readFile.readline().strip()

def run_single_player_game_locally():
    """
    A test harness for local single-player mode, demonstrating two approaches:
     1) place_ships_manually()
     2) place_ships_randomly()

    Then the player tries to sink them by firing coordinates.
    """
    board = Board(BOARD_SIZE)

    # Ask user how they'd like to place ships
    choice = input("Place ships manually (M) or randomly (R)? [M/R]: ").strip().upper()
    if choice == 'M':
        board.place_ships_manually(SHIPS)
    else:
        board.place_ships_randomly(SHIPS)

    print("\nNow try to sink all the ships!")
    moves = 0
    while True:
        board.print_display_grid()
        guess = input("\nEnter coordinate to fire at (or 'quit'): ").strip()
        if guess.lower() == 'quit':
            print("Thanks for playing. Exiting...")
            return

        try:
            row, col = parse_coordinate(guess)
            result, sunk_name = board.fire_at(row, col)
            moves += 1

            if result == 'hit':
                if sunk_name:
                    print(f"  >> HIT! You sank the {sunk_name}!")
                else:
                    print("  >> HIT!")
                if board.all_ships_sunk():
                    board.print_display_grid()
                    print(f"\nCongratulations! You sank all ships in {moves} moves.")
                    break
            elif result == 'miss':
                print("  >> MISS!")
            elif result == 'already_shot':
                print("  >> You've already fired at that location. Try again.")

        except ValueError as e:
            print("  >> Invalid input:", e)


def run_single_player_game_online(rfile, wfile):
    """
    A test harness for running the single-player game with I/O redirected to socket file objects.
    Expects:
      - rfile: file-like object to .readline() from client
      - wfile: file-like object to .write() back to client
    
    #####
    NOTE: This function is (intentionally) currently somewhat "broken", which will be evident if you try and play the game via server/client.
    You can use this as a starting point, or write your own.
    #####
    """
    def send(msg):
        wfile.write(msg + '\n')
        wfile.flush()

    def send_board(board):
        wfile.write("GRID\n")
        wfile.write("  " + " ".join(str(i + 1).rjust(2) for i in range(board.size)) + '\n')
        for r in range(board.size):
            row_label = chr(ord('A') + r)
            row_str = " ".join(board.display_grid[r][c] for c in range(board.size))
            wfile.write(f"{row_label:2} {row_str}\n")
        wfile.write('\n')
        wfile.flush()

    def recv():
        return rfile.readline().strip()

    board = Board(BOARD_SIZE)
    board.place_ships_randomly(SHIPS)

    send("Welcome to Online Single-Player Battleship! Try to sink all the ships. Type 'quit' to exit.")
    print("Server just sent the welcome message...!")

    moves = 0
    while True:
        send_board(board)
        send("Enter coordinate to fire at (e.g. B5):")
        guess = recv()
        print("Received ", guess)
        if guess.lower() == 'quit':
            send("Thanks for playing. Goodbye.")
            return

        try:
            row, col = parse_coordinate(guess)
            result, sunk_name = board.fire_at(row, col)
            moves += 1

            if result == 'hit':
                if sunk_name:
                    send(f"HIT! You sank the {sunk_name}!")
                else:
                    send("HIT!")
                if board.all_ships_sunk():
                    send_board(board)
                    send(f"Congratulations! You sank all ships in {moves} moves.")
                    return
            elif result == 'miss':
                send("MISS!")
            elif result == 'already_shot':
                send("You've already fired at that location.")
        except ValueError as e:
            send(f"Invalid input: {e}")



def run_multi_player_round(clientOne, clientTwo, spectators, newGame, savedOne, savedTwo):

    saveBoardOne = None
    saveBoardTwo = None

    sendWaitMsg = False

    def send(msg, wfile): 
        #print("Type for wfile: ", type(wfile))
        try:
            wfile.write(msg+"\n")
            wfile.flush()
        except (BrokenPipeError, OSError) as e:
            print("[SERVERERROR] Could not send message to client. Client may have disconnected.")
            raise DisconnectError("Client disconnected.")

    def send_board(board, clientWFile):
        clientWFile.write("GRID\n")
        clientWFile.write("  " + " ".join(str(i + 1).rjust(2) for i in range(board.size)) + '\n')
        for r in range(board.size):
            row_label = chr(ord('A') + r)
            row_str = " ".join(board.display_grid[r][c] for c in range(board.size))
            clientWFile.write(f"{row_label:2} {row_str}\n")
        clientWFile.write('')
        clientWFile.flush()

    def send_to_spectators(msg):
        print("Sending to spectators!")
        for spectator in spectators:
            try:
                send(f"[FOR_SPECTATOR:] {msg}", spectator["writeFile"])
            except (BrokenPipeError, OSError) as e:
                print("[SERVERERROR] Could not send message to spectator. Spectator may have disconnected.")

    def send_to_both(msg):
        send(msg, clientOne["writeFile"])
        send(msg, clientTwo["writeFile"])

    def recv(clientRFile):
        return clientRFile.readline().strip()

    # concurrently: each client picks if they want to place randomly or manually. For now, just random. 
       
    ###clientOneBoard = BOARD_SIZE
    ###clientOneBoard.place_ships_randomly(SHIPS)

    ###clientTwoBoard = BOARD_SIZE
    ###clientTwoBoard.place_ships_randomly(SHIPS)

    if newGame:

        clientOne["writeFile"].write("[SERVERINFO] It's your turn to place ships.\n")
        clientOne["writeFile"].flush()

        clientTwo["writeFile"].write(f"[SERVERINFO] Please wait for {clientOne["username"]} to finish placing their ships.\n")
        clientTwo["writeFile"].flush()

        boardOne = Board(BOARD_SIZE)
        network_place_ships(boardOne, clientOne["readFile"], clientOne["writeFile"])

        clientTwo["writeFile"].write("[SERVERINFO] It's your turn to place ships.\n")
        clientTwo["writeFile"].flush()

        clientOne["writeFile"].write(f"[SERVERINFO] Please wait for {clientTwo["username"]} to finish placing their ships.\n")
        clientOne["writeFile"].flush()

        boardTwo = Board(BOARD_SIZE)
        network_place_ships(boardTwo, clientTwo["readFile"], clientTwo["writeFile"])

   
        send_to_both("Welcome to battleships, both your boards have now been generated!!\n")
        send_to_both("[SERVERINFO] You have 10 seconds each turn to make a move, or you will forfeit your game.\n")

        clientOne["board"] = boardOne
        clientTwo["board"] = boardTwo

        clientOne["moves"] = 0
        clientTwo["moves"] = 0

        last_move_time[clientOne["connection"]] = time.time()
        last_move_time[clientTwo["connection"]] = time.time()

    else:
        # Assign boards based on username to ensure correct mapping after reconnect
        if savedOne and savedTwo:
            if clientOne["username"] == savedOne["owner"]:
                clientOne["board"] = savedOne["board"]
                clientTwo["board"] = savedTwo["board"]
            else:
                clientOne["board"] = savedTwo["board"]
                clientTwo["board"] = savedOne["board"]
        clientOne["moves"] = 0
        clientTwo["moves"] = 0

    currentUser = clientOne
    otherUser = clientTwo
    spectatorPlayer = 'Player 1'

    invalidInput = 0


    try:    
        while not gameOverPrompt[0]:

            if gameOverPrompt[0]:
                break

            # if invalidInput is 1, it's the current user's second+ attempt, so we've already received this message.
            if invalidInput == 0 and not sendWaitMsg: 
                send("It's your opponent's turn, hang tight!", otherUser["writeFile"])
                sendWaitMsg = True
                send_board(otherUser["board"], currentUser["writeFile"])
                send("It's your turn! Enter coordinate to fire at (e.g. B5):", currentUser["writeFile"])
                send("[SERVERINFO] Reminder: You have 10 seconds to respond or you'll forfeit your turn.", currentUser["writeFile"])

            # set back to 1 later if we need to prompt the user again / they need another go. 
            invalidInput = 0
        
            #send the opponent board to the current user
            try:

                sock = currentUser["connection"]
                rfile = currentUser["readFile"]
                

                # wait up to 1 second for the user to enter input
                ready, _, _ = select.select([sock], [], [], 1.0)
                if gameOverPrompt[0]:
                    break
                if not ready:
                    continue

                print(gameOverPrompt)
                guess = recv(currentUser["readFile"])
                print("Received ", guess)

                last_move_time[currentUser["connection"]] = time.time()

            except:
                print("[SERVERINFO] The current player disconnected.")
                try:
                    send("Your opponent quit or forfeited! You win!", otherUser["writeFile"])
                except:
                    print("[SERVERINFO] The other player also disconnected.")
                print("HELLOOOO")
                # end the game break
                raise DisconnectError("Client disconnected.")
            

            if guess.lower() == 'quit':
                send("Thanks for playing. Goodbye.", currentUser["writeFile"])
                send("Your opponent quit or forfeited! You win!", otherUser["writeFile"])
                gameOverPrompt[0] = True
                # end the game
                break

            try:
                row, col = parse_coordinate(guess)
                result, sunk_name = otherUser["board"].fire_at(row, col)
                # May need to move this as we don't want the move to count? 
                currentUser["moves"] += 1

                if result == 'hit':
                    if sunk_name:
                        send(f"HIT! You sank the {sunk_name}!",  currentUser["writeFile"])
                        send_to_spectators(f"{spectatorPlayer} sank {sunk_name}!")
                    else:
                        send("HIT!", currentUser["writeFile"])
                        send("Your opponent hit!", otherUser["writeFile"])
                        send_to_spectators(f"{spectatorPlayer} hit!")
                    if otherUser["board"].all_ships_sunk():
                        send_board(otherUser["board"])
                        send(f"Congratulations! You sank all ships in {moves} moves.", currentUser["writeFile"])
                        send_to_both("The game is over. Would you like to play again?")
                        send_to_spectators("A game has ended.")
                        gameOverPrompt[0] = True
                        return
                elif result == 'miss':
                    send("MISS!",  currentUser["writeFile"])
                    send("Your opponent missed!", otherUser["writeFile"])
                    send_to_spectators(f"{spectatorPlayer} missed!")
                elif result == 'already_shot':
                    send("You've already fired at that location.", currentUser["writeFile"])
            except ValueError as e:
                send(f"Invalid input: Your coordinate should take the format (letter,number)",  currentUser["writeFile"])
                currentUser["moves"] -=1 
                invalidInput = 1
            except IndexError as e: 
                send(f"Invalid input, your number and letter should be on the grid!", currentUser["writeFile"])
                currentUser["moves"] -=1 
                invalidInput = 1
            
            #don't change the current users, as we want to give the user another turn. 
            if invalidInput == 1:
            # print("This should be sending the input prompt back to the user who entered incorrectly...")
                pass 
            #don't change the current users
            else:
                if currentUser == clientOne: 
                    currentUser = clientTwo
                    otherUser = clientOne
                    spectatorPlayer = 'Player 2'
                else:
                    currentUser = clientOne
                    otherUser = clientTwo
                    spectatorPlayer = 'Player 1'

            # if the game is over, we need to break out of the loop #after each turn, save the board state. 
                saveBoardOne = {"owner": clientOne["username"], "board": clientOne["board"]}
                saveBoardTwo = {"owner": clientTwo["username"], "board": clientTwo["board"]}
            
                sendWaitMsg = False
            

            
            # once they have both places boards, the game can begin: 

            # server prompts player one. 
            # player one makes a move on player 2's board. 
            # Server responds to both player 1 and player 2 with effectively same message
            # Server prompts player two.
            # Player 2 makes a move on player 1's board. 
            # etc. 
    except DisconnectError:
        print("[SERVERINFO] A player disconnected. Ending game loop.")
        try:
            send("Your opponent quit or forfeited! You win!", otherUser["writeFile"])
        except:
            print("[SERVERINFO] The other player also disconnected.")
        print("did it reach here")

        gameOverPrompt[0] = True
        return saveBoardOne, saveBoardTwo
        #raise Exception("Game ended due to disconnect or timeout")


if __name__ == "__main__":
    # Optional: run this file as a script to test single-player mode
    run_single_player_game_locally()
