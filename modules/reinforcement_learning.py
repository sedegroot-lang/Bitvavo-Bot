"""
Reinforcement Learning Module
Q-Learning agent for adaptive trading decisions
"""

import json
import logging
import math
import random
from collections import defaultdict, deque
from pathlib import Path
from typing import Dict, Tuple

LOGGER = logging.getLogger(__name__)


class QLearningAgent:
    """
    Q-Learning agent for trading decisions

    State: (trend, volatility, rsi_zone, position_status)
    Actions: BUY, HOLD, SELL
    """

    def __init__(
        self,
        learning_rate: float = 0.1,
        discount_factor: float = 0.95,
        epsilon: float = 0.1,
        state_file: str = "models/q_table.json",
        epsilon_min: float = 0.01,
        epsilon_decay: float = 0.995,
        log_states: bool = False,
    ):
        self.alpha = learning_rate  # Learning rate
        self.gamma = discount_factor  # Discount factor
        self.epsilon = epsilon  # Exploration rate
        self.epsilon_min = epsilon_min
        self.epsilon_decay = epsilon_decay
        self.log_states = log_states
        self.state_file = Path(state_file)

        # Q-table: {state: {action: q_value}}
        self.q_table: Dict[str, Dict[str, float]] = defaultdict(lambda: {"BUY": 0.0, "HOLD": 0.0, "SELL": 0.0})

        # Experience replay buffer
        self.replay_buffer: deque = deque(maxlen=1000)

        self._load_q_table()

    def _load_q_table(self):
        """Load Q-table from disk"""
        if not self.state_file.exists():
            return

        try:
            with open(self.state_file, "r") as f:
                data = json.load(f)
                for state, actions in data.items():
                    self.q_table[state] = actions
        except Exception:
            pass

    def save_q_table(self):
        """Save Q-table to disk"""
        self.state_file.parent.mkdir(parents=True, exist_ok=True)

        with open(self.state_file, "w") as f:
            json.dump(dict(self.q_table), f, indent=2)

    def get_state(self, market_data: Dict) -> str:
        """
        Convert market data to discrete state

        Args:
            market_data: {
                'trend': 'bullish'|'bearish'|'neutral',
                'volatility': float (0-1),
                'rsi': float (0-100),
                'has_position': bool
            }

        Returns: state string like "bullish_high_oversold_open"
        """
        trend = market_data.get("trend", "neutral")
        volatility = market_data.get("volatility", 0.0)
        rsi = market_data.get("rsi", 50)
        has_position = market_data.get("has_position", False)

        # Discretize volatility
        if volatility < 0.01:
            vol_zone = "low"
        elif volatility < 0.03:
            vol_zone = "medium"
        else:
            vol_zone = "high"

        # Discretize RSI
        if rsi < 30:
            rsi_zone = "oversold"
        elif rsi < 45:
            rsi_zone = "low"
        elif rsi < 55:
            rsi_zone = "neutral"
        elif rsi < 70:
            rsi_zone = "high"
        else:
            rsi_zone = "overbought"

        position_status = "open" if has_position else "closed"

        state = f"{trend}_{vol_zone}_{rsi_zone}_{position_status}"

        return state

    def choose_action(self, state: str, explore: bool = True) -> str:
        """
        Choose action using epsilon-greedy policy

        Args:
            state: Current state string
            explore: If True, use epsilon-greedy; if False, always exploit

        Returns: 'BUY', 'HOLD', or 'SELL'
        """
        if explore and random.random() < self.epsilon:
            # Explore: random action
            return random.choice(["BUY", "HOLD", "SELL"])
        else:
            # Exploit: best action
            q_values = self.q_table[state]
            best_action = max(q_values, key=q_values.get)
            return best_action

    def update(self, state: str, action: str, reward: float, next_state: str):
        """
        Update Q-table using Q-learning formula

        Q(s,a) = Q(s,a) + α * (reward + γ * max(Q(s',a')) - Q(s,a))
        """
        current_q = self.q_table[state][action]
        max_next_q = max(self.q_table[next_state].values())

        new_q = current_q + self.alpha * (reward + self.gamma * max_next_q - current_q)

        self.q_table[state][action] = new_q

        # Add to replay buffer
        self.replay_buffer.append((state, action, reward, next_state))
        self._log_state_transition(state, action, reward, next_state)
        self._decay_epsilon()

    def replay_experience(self, batch_size: int = 32):
        """
        Experience replay: learn from past experiences
        """
        if len(self.replay_buffer) < batch_size:
            return

        batch = random.sample(self.replay_buffer, batch_size)

        for state, action, reward, next_state in batch:
            current_q = self.q_table[state][action]
            max_next_q = max(self.q_table[next_state].values())

            new_q = current_q + self.alpha * (reward + self.gamma * max_next_q - current_q)
            self.q_table[state][action] = new_q

    def get_q_values(self, state: str) -> Dict[str, float]:
        """Get Q-values for all actions in given state"""
        return self.q_table[state].copy()

    def get_best_action_value(self, state: str) -> Tuple[str, float]:
        """Get best action and its Q-value for given state"""
        q_values = self.q_table[state]
        best_action = max(q_values, key=q_values.get)
        best_value = q_values[best_action]

        return (best_action, best_value)

    def _decay_epsilon(self):
        """Decay exploration rate with lower bound"""
        if self.epsilon <= self.epsilon_min:
            self.epsilon = self.epsilon_min
            return
        self.epsilon = max(self.epsilon * self.epsilon_decay, self.epsilon_min)

    def _log_state_transition(self, state: str, action: str, reward: float, next_state: str):
        """Optional trace logging for RL transitions"""
        if not self.log_states:
            return
        LOGGER.info(
            "RL transition state=%s action=%s reward=%.4f next_state=%s epsilon=%.4f",
            state,
            action,
            reward,
            next_state,
            self.epsilon,
        )


class RewardCalculator:
    """Calculate rewards for RL agent"""

    @staticmethod
    def calculate_trade_reward(pnl_pct: float, hold_hours: float, risk_adjusted: bool = True) -> float:
        """
        Calculate reward for a completed trade

        Args:
            pnl_pct: Profit/loss percentage
            hold_hours: How long position was held
            risk_adjusted: If True, penalize long holds and reward quick wins

        Returns: reward value
        """
        # Base reward from P/L
        base_reward = pnl_pct * 10  # Scale up for learning

        if not risk_adjusted:
            return base_reward

        # Time penalty: prefer quick wins
        time_penalty = 0.0
        if hold_hours > 48:  # After 2 days
            time_penalty = (hold_hours - 48) * 0.01

        # Risk adjustment: big wins get bonus, big losses get extra penalty
        if pnl_pct > 5:
            base_reward *= 1.5  # Bonus for big wins
        elif pnl_pct < -5:
            base_reward *= 1.5  # Extra penalty for big losses

        total_reward = base_reward - time_penalty

        return total_reward

    @staticmethod
    def calculate_step_reward(price_change_pct: float, has_position: bool) -> float:
        """
        Calculate reward for each time step (e.g., hourly)

        Args:
            price_change_pct: Price change since last step
            has_position: Whether agent has open position

        Returns: reward value
        """
        if not has_position:
            return 0.0  # No reward if no position

        # Reward based on price movement
        return price_change_pct * 1.0


class AdaptiveTradingAgent:
    """
    Adaptive trading agent using Q-learning
    Learns optimal actions based on market conditions
    """

    def __init__(self, config_path: str = "config/bot_config.json"):
        self.config_path = Path(config_path)
        self.config = self._load_config()

        # RL parameters
        learning_rate = self.config.get("RL_LEARNING_RATE", 0.1)
        discount_factor = self.config.get("RL_DISCOUNT_FACTOR", 0.95)
        epsilon = self.config.get("RL_EPSILON", 0.1)
        epsilon_min = self.config.get("RL_EPSILON_MIN", 0.01)
        epsilon_decay = self.config.get("RL_EPSILON_DECAY", 0.995)
        log_states = self.config.get("RL_LOG_STATES", False)

        self.agent = QLearningAgent(
            learning_rate,
            discount_factor,
            epsilon,
            epsilon_min=epsilon_min,
            epsilon_decay=epsilon_decay,
            log_states=log_states,
        )
        self.reward_calc = RewardCalculator()

        # Training mode
        self.training_mode = self.config.get("RL_TRAINING_MODE", False)

    def _load_config(self) -> Dict:
        """Load configuration"""
        if not self.config_path.exists():
            return {}

        try:
            with open(self.config_path, "r") as f:
                return json.load(f)
        except Exception:
            return {}

    def decide_action(self, market_data: Dict) -> str:
        """
        Decide trading action based on current market state

        Returns: 'BUY', 'HOLD', or 'SELL'
        """
        state = self.agent.get_state(market_data)
        action = self.agent.choose_action(state, explore=self.training_mode)

        return action

    def learn_from_trade(self, entry_state: Dict, action: str, exit_state: Dict, pnl_pct: float, hold_hours: float):
        """
        Learn from completed trade

        Args:
            entry_state: Market state at entry
            action: Action taken ('BUY')
            exit_state: Market state at exit
            pnl_pct: Profit/loss percentage
            hold_hours: Hold duration
        """
        if not self.training_mode:
            return

        state = self.agent.get_state(entry_state)
        next_state = self.agent.get_state(exit_state)

        reward = self.reward_calc.calculate_trade_reward(pnl_pct, hold_hours)

        self.agent.update(state, action, reward, next_state)

        # Periodic experience replay
        if random.random() < 0.1:  # 10% chance
            self.agent.replay_experience()

    def save_model(self):
        """Save learned Q-table"""
        self.agent.save_q_table()

    def get_action_confidence(self, market_data: Dict) -> Dict[str, float]:
        """
        Get confidence scores for all actions
        Returns normalized probabilities
        """
        state = self.agent.get_state(market_data)
        q_values = self.agent.get_q_values(state)

        # Softmax to convert Q-values to probabilities
        exp_values = {action: math.exp(q / 10.0) for action, q in q_values.items()}
        total = sum(exp_values.values())

        if total == 0:
            return {"BUY": 0.33, "HOLD": 0.33, "SELL": 0.34}

        probabilities = {action: exp_val / total for action, exp_val in exp_values.items()}

        return probabilities


def get_rl_agent() -> AdaptiveTradingAgent:
    """Get RL agent instance"""
    return AdaptiveTradingAgent()
