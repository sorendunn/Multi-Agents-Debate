import os
import sys
import json
import random
import jsonlines
import concurrent.futures
from code.utils.agent import Agent
random.seed(0)

openai_api_key = os.getenv("OPENAI_API_KEY")

NAME_LIST=[
    "Affirmative side",
    "Negative side",
    "Moderator",
]

class DebatePlayer(Agent):
    def __init__(self, model_name: str, name: str, temperature:float, openai_api_key: str, sleep_time: float) -> None:
        """Create a player in the debate

        Args:
            model_name(str): model name
            name (str): name of this player
            temperature (float): higher values make the output more random, while lower values make it more focused and deterministic
            openai_api_key (str): As the parameter name suggests
            sleep_time (float): sleep because of rate limits
        """
        super(DebatePlayer, self).__init__(model_name, name, temperature, sleep_time)
        self.openai_api_key = openai_api_key


class Debate:
    def __init__(self,
        writer,
        model_name: str='gpt-3.5-turbo', 
        temperature: float=0, 
        num_players: int=3, 
        openai_api_key: str=None,
        config: dict=None,
        max_round: int=3,
        sleep_time: float=0) -> None:
        """Create a debate

        Args:
            model_name (str): openai model name
            temperature (float): higher values make the output more random, while lower values make it more focused and deterministic
            num_players (int): num of players
            openai_api_key (str): As the parameter name suggests
            max_round (int): maximum Rounds of Debate
            sleep_time (float): sleep because of rate limits
        """

        self.model_name = model_name
        self.temperature = temperature
        self.num_players = num_players
        self.openai_api_key = openai_api_key
        self.config = config
        self.max_round = max_round
        self.sleep_time = sleep_time

        self.init_prompt()

        # creat&init agents
        self.creat_agents()
        self.init_agents()

        self.writer = writer
        
    def init_prompt(self):
        def prompt_replace(key):
            self.config[key] = self.config[key].replace("##debate_topic##", self.config["debate_topic"])
        prompt_replace("player_meta_prompt")
        prompt_replace("moderator_meta_prompt")
        prompt_replace("affirmative_prompt")
        prompt_replace("judge_prompt_last2")

    def creat_agents(self):
        # creates players
        self.players = [
            DebatePlayer(model_name=self.model_name, name=name, temperature=self.temperature, openai_api_key=self.openai_api_key, sleep_time=self.sleep_time) for name in NAME_LIST
        ]
        self.affirmative = self.players[0]
        self.negative = self.players[1]
        self.moderator = self.players[2]

    def init_agents(self):
        # start: set meta prompt
        self.affirmative.set_meta_prompt(self.config['player_meta_prompt'])
        self.negative.set_meta_prompt(self.config['player_meta_prompt'])
        self.moderator.set_meta_prompt(self.config['moderator_meta_prompt'])
        
        # start: first round debate, state opinions
        print(f"===== Debate Round-1 =====\n")
        self.affirmative.add_event(self.config['affirmative_prompt'])
        self.aff_ans = self.affirmative.ask()
        self.affirmative.add_memory(self.aff_ans)
        self.config['base_answer'] = self.aff_ans

        self.negative.add_event(self.config['negative_prompt'].replace('##aff_ans##', self.aff_ans))
        self.neg_ans = self.negative.ask()
        self.negative.add_memory(self.neg_ans)

        self.moderator.add_event(self.config['moderator_prompt'].replace('##aff_ans##', self.aff_ans).replace('##neg_ans##', self.neg_ans).replace('##round##', 'first'))
        self.mod_ans = self.moderator.ask()
        self.moderator.add_memory(self.mod_ans)
        self.mod_ans = eval(self.mod_ans)

    def round_dct(self, num: int):
        dct = {
            1: 'first', 2: 'second', 3: 'third', 4: 'fourth', 5: 'fifth', 6: 'sixth', 7: 'seventh', 8: 'eighth', 9: 'ninth', 10: 'tenth'
        }
        return dct[num]

    def run(self):
        print("got into one debate")
        for round in range(self.max_round - 1):

            if (self.mod_ans["debate_answer"] != ''): # and (round + 2 > 2)
                break
            else:
                print(f"===== Debate Round-{round+2} =====\n")
                self.affirmative.add_event(self.config['debate_prompt'].replace('##oppo_ans##', self.neg_ans))
                self.aff_ans = self.affirmative.ask()
                self.affirmative.add_memory(self.aff_ans)

                self.negative.add_event(self.config['debate_prompt'].replace('##oppo_ans##', self.aff_ans))
                self.neg_ans = self.negative.ask()
                self.negative.add_memory(self.neg_ans)

                self.moderator.add_event(self.config['moderator_prompt'].replace('##aff_ans##', self.aff_ans).replace('##neg_ans##', self.neg_ans).replace('##round##', self.round_dct(round+2)))
                self.mod_ans = self.moderator.ask()
                self.moderator.add_memory(self.mod_ans)
                self.mod_ans = eval(self.mod_ans)

        if self.mod_ans["debate_answer"] != '':
            self.config.update(self.mod_ans)
            self.config['success'] = True

        # ultimate deadly technique.
        else:
            judge_player = DebatePlayer(model_name=self.model_name, name='Judge', temperature=self.temperature, openai_api_key=self.openai_api_key, sleep_time=self.sleep_time)
            aff_ans = self.affirmative.memory_lst[2]['content']
            neg_ans = self.negative.memory_lst[2]['content']

            judge_player.set_meta_prompt(self.config['moderator_meta_prompt'])

            # extract answer candidates
            judge_player.add_event(self.config['judge_prompt_last1'].replace('##aff_ans##', aff_ans).replace('##neg_ans##', neg_ans))
            ans = judge_player.ask()
            judge_player.add_memory(ans)

            # select one from the candidates
            judge_player.add_event(self.config['judge_prompt_last2'])
            ans = judge_player.ask()
            judge_player.add_memory(ans)
            
            ans = eval(ans)
            if ans["debate_answer"] != '':
                self.config['success'] = True
                # save file
            self.config.update(ans)
            self.players.append(judge_player)

        self.print_answer()

    def speak(self, speaker: str, msg: str):
        if not msg.startswith(f"{speaker}: "):
            msg = f"{speaker}: {msg}"
        for player in self.players:
            if player.name != speaker:
                player.add_event(msg)

    def print_answer(self):
        debate_output = {
            "Debate Topic": self.config["debate_topic"],
            "Base Answer": self.config["base_answer"],
            "Debate Answer": self.config["debate_answer"],
            "Debate Reason": self.config["Reason"]
        }
        self.writer.write(debate_output)

def run_debate(item, writer, openai_api_key):
    config = json.load(open(f"{MAD_path}/code/utils/config4all.json", "r"))
    print("it started running debate")
    question, response = list(item.items())[0]
    config['debate_topic'] = question
    debate = Debate(writer=writer, num_players=3, openai_api_key=openai_api_key, config=config, temperature=0, sleep_time=0)
    debate.run()

if __name__ == "__main__":
    current_script_path = os.path.abspath(__file__)
    MAD_path = current_script_path.rsplit("\\", 1)[0]
    output_file_path = sys.argv[2]

    with open(sys.argv[1], "r") as f:
        data = [json.loads(line) for line in f]

    with jsonlines.open(output_file_path, mode='w') as writer:
        with concurrent.futures.ThreadPoolExecutor() as executor:
            for item in data:
                executor.submit(run_debate, item, writer, openai_api_key)