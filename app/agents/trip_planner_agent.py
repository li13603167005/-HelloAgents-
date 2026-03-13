
"""多智能体旅行规划系统"""
import os
import concurrent.futures
import json
from typing import Dict, Any, List
from hello_agents import SimpleAgent
from hello_agents.tools import MCPTool
from ..services.llm_service import get_llm
from ..models.schemas import TripRequest, TripPlan, DayPlan, Attraction, Meal, WeatherInfo, Location, Hotel
from ..config import get_settings

# ============ Agent提示词 ============

ATTRACTION_AGENT_PROMPT = """你是景点搜索专家。你的任务是根据城市和用户偏好搜索合适的景点。

**重要提示:**
你必须使用工具来搜索景点!不要自己编造景点信息!

**工具调用格式:**
请使用 maps_text_search 工具，必须严格按照以下格式:
`[TOOL_CALL:maps_text_search:keywords=景点关键词,city=城市名]`

**示例:**
用户: "搜索北京的历史文化景点"
你的回复: [TOOL_CALL:maps_text_search:keywords=历史文化,city=北京]

用户: "搜索上海的公园"
你的回复: [TOOL_CALL:maps_text_search:keywords=公园,city=上海]
"""

WEATHER_AGENT_PROMPT = """你是天气查询专家。你的任务是查询指定城市的天气信息。

**重要提示:**
你必须使用工具来查询天气!不要自己编造天气信息!

**工具调用格式:**
请使用 maps_weather 工具，必须严格按照以下格式:
`[TOOL_CALL:maps_weather:city=城市名]`

**示例:**
用户: "查询北京天气"
你的回复: [TOOL_CALL:maps_weather:city=北京]
"""

HOTEL_AGENT_PROMPT = """你是酒店推荐专家。你的任务是根据城市和景点位置推荐合适的酒店。

**重要提示:**
你必须使用工具来搜索酒店!不要自己编造酒店信息!

**工具调用格式:**
请使用 maps_text_search 工具，必须严格按照以下格式:
`[TOOL_CALL:maps_text_search:keywords=酒店,city=城市名]`

**示例:**
用户: "搜索北京的酒店"
你的回复: [TOOL_CALL:maps_text_search:keywords=酒店,city=北京]
"""

PLANNER_AGENT_PROMPT = """你是行程规划专家。你的任务是根据景点、天气和酒店信息，生成详细的旅行计划。

**核心约束:**
1. 每天必须安排2-3个景点,并考虑合理距离。
2. 每天必须包含早、中、晚三餐。
3. 景点的经纬度坐标必须真实准确。
4. 提供实用的旅行建议和精确的预算信息。

**输出格式要求:**
你必须严格按照提供的 JSON Schema 格式输出结果。
不要包含任何额外的解释性文本、Markdown 标记（如 ```json)或思考过程。
只输出纯净的、可被 Python json.loads() 解析的 JSON 字符串！
"""


class MultiAgentTripPlanner:
    """多智能体旅行规划系统"""

    def __init__(self):
        """初始化多智能体系统"""
        print("🔄 开始初始化多智能体旅行规划系统...")

        try:
            settings = get_settings()
            self.llm = get_llm()

          # 创建共享的MCP工具(只创建一次)
            print("  - 连接独立的 MCP 微服务...")
            self.amap_tool = MCPTool(
                name="amap",
                description="高德地图服务",
                # 👇 彻底抛弃繁重的本地进程管理，改为轻量的网络 SSE 连接
                server_url="http://localhost:8080/sse",
                auto_expand=True 
            )

            # 创建景点搜索Agent
            print("  - 创建景点搜索Agent...")
            self.attraction_agent = SimpleAgent(
                name="景点搜索专家",
                llm=self.llm,
                system_prompt=ATTRACTION_AGENT_PROMPT
            )
            self.attraction_agent.add_tool(self.amap_tool)

            # 创建天气查询Agent
            print("  - 创建天气查询Agent...")
            self.weather_agent = SimpleAgent(
                name="天气查询专家",
                llm=self.llm,
                system_prompt=WEATHER_AGENT_PROMPT
            )
            self.weather_agent.add_tool(self.amap_tool)

            # 创建酒店推荐Agent
            print("  - 创建酒店推荐Agent...")
            self.hotel_agent = SimpleAgent(
                name="酒店推荐专家",
                llm=self.llm,
                system_prompt=HOTEL_AGENT_PROMPT
            )
            self.hotel_agent.add_tool(self.amap_tool)

            # 创建行程规划Agent(不需要工具)
            print("  - 创建行程规划Agent...")
            self.planner_agent = SimpleAgent(
                name="行程规划专家",
                llm=self.llm,
                system_prompt=PLANNER_AGENT_PROMPT
            )

            print(f"✅ 多智能体系统初始化成功")
            print(f"   景点搜索Agent: {len(self.attraction_agent.list_tools())} 个工具")
            print(f"   天气查询Agent: {len(self.weather_agent.list_tools())} 个工具")
            print(f"   酒店推荐Agent: {len(self.hotel_agent.list_tools())} 个工具")

        except Exception as e:
            print(f"❌ 多智能体系统初始化失败: {str(e)}")
            import traceback
            traceback.print_exc()
            raise
    
    def plan_trip(self, request: TripRequest) -> TripPlan:
        """
        使用多智能体协作生成旅行计划

        Args:
            request: 旅行请求

        Returns:
            旅行计划
        """
        try:
            print(f"\n{'='*60}")
            print(f"🚀 开始多智能体协作规划旅行...")
            print(f"目的地: {request.city}")
            print(f"日期: {request.start_date} 至 {request.end_date}")
            print(f"天数: {request.travel_days}天")
            print(f"偏好: {', '.join(request.preferences) if request.preferences else '无'}")
            print(f"{'='*60}\n")

# 准备查询语句
            attraction_query = self._build_attraction_query(request)
            weather_query = f"请查询{request.city}的天气信息"
            hotel_query = f"请搜索{request.city}的{request.accommodation}酒店"

            print("⚡ 开启多线程并发查询：同时获取景点、天气、酒店数据...")
            
            # 使用线程池并发执行 3 个 Agent 的外部请求，并接入重试机制
            with concurrent.futures.ThreadPoolExecutor(max_workers=3) as executor:
                # 提交任务到线程池 (使用新写的状态机路由方法)
                future_attraction = executor.submit(self._run_agent_with_retry, self.attraction_agent, attraction_query, "景点搜索节点")
                future_weather = executor.submit(self._run_agent_with_retry, self.weather_agent, weather_query, "天气查询节点")
                future_hotel = executor.submit(self._run_agent_with_retry, self.hotel_agent, hotel_query, "酒店搜索节点")

                # 等待并获取结果
                attraction_response = future_attraction.result()
                weather_response = future_weather.result()
                hotel_response = future_hotel.result()

            print(f"📍 景点搜索结果: {attraction_response[:100]}...\n")
            print(f"🌤️ 天气查询结果: {weather_response[:100]}...\n")
            print(f"🏨 酒店搜索结果: {hotel_response[:100]}...\n")

            # 步骤4: 行程规划Agent整合信息生成计划 (这一步必须等待前三步完成)
            print("📋 步骤4: 生成行程计划...")
            planner_query = self._build_planner_query(request, attraction_response, weather_response, hotel_response)
            planner_response = self.planner_agent.run(planner_query)
            print(f"行程规划结果: {planner_response[:100]}...\n")

            # 步骤4: 行程规划Agent整合信息生成计划
            print("📋 步骤4: 生成行程计划...")
            planner_query = self._build_planner_query(request, attraction_response, weather_response, hotel_response)
            planner_response = self.planner_agent.run(planner_query)
            print(f"行程规划结果: {planner_response[:300]}...\n")

            # 解析最终计划
            trip_plan = self._parse_response(planner_response, request)

            print(f"{'='*60}")
            print(f"✅ 旅行计划生成完成!")
            print(f"{'='*60}\n")

            return trip_plan

        except Exception as e:
            print(f"❌ 生成旅行计划失败: {str(e)}")
            import traceback
            traceback.print_exc()
            return self._create_fallback_plan(request)

    def _run_agent_with_retry(self, agent, query: str, node_name: str, max_retries: int = 2) -> str:
        """
        轻量级图状态机(Graph)：带有反思(Reflection)机制的执行节点
        """
        current_query = query
        last_response = ""
        
        for attempt in range(max_retries):
            # 1. 节点执行：运行 Agent
            response = agent.run(current_query)
            
            # 2. 状态校验：检查工具调用是否返回了典型的失败特征
            error_keywords = ["很抱歉", "无法", "失败", "不支持", "暂时不可用"]
            is_failed = any(keyword in response for keyword in error_keywords)
            
            if not is_failed:
                # 成功流转：跳出循环，返回正确结果
                if attempt > 0:
                    print(f"🔄 [{node_name}] 第 {attempt + 1} 次重试(反思)成功！")
                return response
                
            # 3. 失败反思流转：构建反思 Prompt，进入下一次循环
            print(f"⚠️ [{node_name}] 第 {attempt + 1} 次执行失败，触发反思重试机制...")
            last_response = response
            # 将错误信息作为上下文喂给大模型，让它换个思路
            current_query = f"""
上一次我请求你执行的任务是：{query}
但是你(或工具)返回了错误结果：{response}

请反思失败原因。如果是工具不支持当前搜索词，请尝试更换更通用的关键词（例如去掉生僻字，或者将具体名称改为广泛的类别）再次调用工具！
"""
        
        # 4. 兜底流转：达到最大重试次数，返回最后一次的结果
        print(f"❌ [{node_name}] 达到最大重试次数 ({max_retries})，节点流转结束。")
        return last_response
    
    def _build_attraction_query(self, request: TripRequest) -> str:
        """构建景点搜索查询 - 直接包含工具调用"""
        keywords = []
        if request.preferences:
            # 只取第一个偏好作为关键词
            keywords = request.preferences[0]
        else:
            keywords = "景点"

        # 直接返回工具调用格式
        query = f"请搜索{request.city}的{keywords}相关景点。"
        return query

    def _build_planner_query(self, request: TripRequest, attractions: str, weather: str, hotels: str = "") -> str:
        """构建行程规划查询"""
        target_schema = json.dumps(TripPlan.model_json_schema(), ensure_ascii=False)
        query = f"""请根据以下信息生成{request.city}的{request.travel_days}天旅行计划:

**基本信息:**
- 城市: {request.city}
- 日期: {request.start_date} 至 {request.end_date}
- 天数: {request.travel_days}天
- 交通方式: {request.transportation}
- 住宿: {request.accommodation}
- 偏好: {', '.join(request.preferences) if request.preferences else '无'}

**景点信息:**
{attractions}

**天气信息:**
{weather}

**酒店信息:**
{hotels}

**要求:**
1. 每天安排2-3个景点
2. 每天必须包含早中晚三餐
3. 每天推荐一个具体的酒店(从酒店信息中选择)
3. 考虑景点之间的距离和交通方式
4. 返回完整的JSON格式数据
5. 景点的经纬度坐标要真实准确
"""
        if request.free_text_input:
            query += f"\n**额外要求:** {request.free_text_input}"

        return query
    
    def _parse_response(self, response: str, request: TripRequest) -> TripPlan:
        import json

        try:
            # 1. 基础的 Markdown 剥离兜底
            cleaned_response = response.strip()
            if cleaned_response.startswith("```json"):
                cleaned_response = cleaned_response[7:]
            elif cleaned_response.startswith("```"):
                cleaned_response = cleaned_response[3:]
            if cleaned_response.endswith("```"):
                cleaned_response = cleaned_response[:-3]
            cleaned_response = cleaned_response.strip()

            # 2. 尝试解析 JSON
            data = json.loads(cleaned_response)
            
            # 3. 核心：让 Pydantic 进行深层校验！
            # 任何类型错误、必填项缺失都会在这里被拦截报错
            # 如果是 Pydantic v1, 请换成 TripPlan.parse_obj(data)
            trip_plan = TripPlan.model_validate(data) 
            
            print("✅ 结构化数据解析与 Pydantic 契约校验完美通过！")
            return trip_plan
            
        except json.JSONDecodeError as e:
            print(f"⚠️ 致命错误: 大模型输出了非标准 JSON! 详情: {str(e)}")
            print(f"异常响应片段: {response[:300]}...")
            return self._create_fallback_plan(request)
        except Exception as e:
            # 捕获 Pydantic 的 ValidationError
            print(f"⚠️ 契约违背: JSON 结构与 Pydantic 模型不匹配! 详情: {str(e)}")
            return self._create_fallback_plan(request)
        
    
    def _create_fallback_plan(self, request: TripRequest) -> TripPlan:
        """创建备用计划(当Agent失败时)"""
        from datetime import datetime, timedelta
        
        # 解析日期
        start_date = datetime.strptime(request.start_date, "%Y-%m-%d")
        
        # 创建每日行程
        days = []
        for i in range(request.travel_days):
            current_date = start_date + timedelta(days=i)
            
            day_plan = DayPlan(
                date=current_date.strftime("%Y-%m-%d"),
                day_index=i,
                description=f"第{i+1}天行程",
                transportation=request.transportation,
                accommodation=request.accommodation,
                attractions=[
                    Attraction(
                        name=f"{request.city}景点{j+1}",
                        address=f"{request.city}市",
                        location=Location(longitude=116.4 + i*0.01 + j*0.005, latitude=39.9 + i*0.01 + j*0.005),
                        visit_duration=120,
                        description=f"这是{request.city}的著名景点",
                        category="景点"
                    )
                    for j in range(2)
                ],
                meals=[
                    Meal(type="breakfast", name=f"第{i+1}天早餐", description="当地特色早餐"),
                    Meal(type="lunch", name=f"第{i+1}天午餐", description="午餐推荐"),
                    Meal(type="dinner", name=f"第{i+1}天晚餐", description="晚餐推荐")
                ]
            )
            days.append(day_plan)
        
        return TripPlan(
            city=request.city,
            start_date=request.start_date,
            end_date=request.end_date,
            days=days,
            weather_info=[],
            overall_suggestions=f"这是为您规划的{request.city}{request.travel_days}日游行程,建议提前查看各景点的开放时间。"
        )


# 全局多智能体系统实例
_multi_agent_planner = None


def get_trip_planner_agent() -> MultiAgentTripPlanner:
    """获取多智能体旅行规划系统实例(单例模式)"""
    global _multi_agent_planner

    if _multi_agent_planner is None:
        _multi_agent_planner = MultiAgentTripPlanner()

    return _multi_agent_planner

