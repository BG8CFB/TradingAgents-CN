#!/usr/bin/env python3
"""
中国财经数据聚合工具
由于微博API申请困难且功能受限，采用多源数据聚合的方式
"""

import requests
import json
import time
from datetime import datetime, timedelta
from app.utils.time_utils import now_utc, now_config_tz, format_date_short, format_date_compact, format_iso
from typing import List, Dict, Optional
import re
from bs4 import BeautifulSoup
import pandas as pd


class ChineseFinanceDataAggregator:
    """中国财经数据聚合器"""
    
    def __init__(self):
        self.headers = {
            'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/91.0.4472.124 Safari/537.36'
        }
        self.session = requests.Session()
        self.session.headers.update(self.headers)
    
    def get_stock_sentiment_summary(self, ticker: str, days: int = 7) -> Dict:
        """
        获取股票情绪分析汇总
        整合多个可获取的中国财经数据源
        """
        try:
            # 1. 获取财经新闻情绪
            news_sentiment = self._get_finance_news_sentiment(ticker, days)
            
            # 2. 获取股吧讨论热度 (如果可以获取)
            forum_sentiment = self._get_stock_forum_sentiment(ticker, days)
            
            # 3. 获取财经媒体报道
            media_sentiment = self._get_media_coverage_sentiment(ticker, days)
            
            # 4. 综合分析
            overall_sentiment = self._calculate_overall_sentiment(
                news_sentiment, forum_sentiment, media_sentiment
            )
            
            return {
                'ticker': ticker,
                'analysis_period': f'{days} days',
                'overall_sentiment': overall_sentiment,
                'news_sentiment': news_sentiment,
                'forum_sentiment': forum_sentiment,
                'media_sentiment': media_sentiment,
                'summary': self._generate_sentiment_summary(overall_sentiment),
                'timestamp': format_iso(now_utc())
            }
            
        except Exception as e:
            return {
                'ticker': ticker,
                'error': f'数据获取失败: {str(e)}',
                'fallback_message': '由于中国社交媒体API限制，建议使用财经新闻和基本面分析作为主要参考',
                'timestamp': format_iso(now_utc())
            }
    
    def _get_finance_news_sentiment(self, ticker: str, days: int) -> Dict:
        """获取财经新闻情绪分析，复用 RealtimeNewsAggregator"""
        try:
            hours_back = days * 24
            news_items = []
            news_titles = []

            # 优先使用 RealtimeNewsAggregator 获取真实新闻
            try:
                from app.data.news.realtime_news import RealtimeNewsAggregator
                aggregator = RealtimeNewsAggregator()
                items = aggregator.get_realtime_stock_news(ticker, hours_back=hours_back, max_news=20)
                if items:
                    news_items = [{'title': item.title, 'content': item.content or ''} for item in items]
                    news_titles = [item.title for item in items[:3]]
            except Exception as e:
                import logging
                logging.getLogger(__name__).warning(f"RealtimeNewsAggregator 获取新闻失败: {e}")

            # 如果实时聚合器没有数据，再尝试本地搜索
            if not news_items:
                company_name = self._get_company_chinese_name(ticker)
                search_terms = [ticker, company_name] if company_name else [ticker]
                for term in search_terms:
                    items = self._search_finance_news(term, days)
                    news_items.extend(items)

            # 简单的情绪分析
            positive_count = 0
            negative_count = 0
            neutral_count = 0

            for item in news_items:
                sentiment = self._analyze_text_sentiment(item.get('title', '') + ' ' + item.get('content', ''))
                if sentiment > 0.1:
                    positive_count += 1
                elif sentiment < -0.1:
                    negative_count += 1
                else:
                    neutral_count += 1

            total = len(news_items)
            if total == 0:
                return {'sentiment_score': 0, 'confidence': 0, 'news_count': 0}

            sentiment_score = (positive_count - negative_count) / total

            return {
                'sentiment_score': sentiment_score,
                'positive_ratio': positive_count / total,
                'negative_ratio': negative_count / total,
                'neutral_ratio': neutral_count / total,
                'news_count': total,
                'confidence': min(total / 10, 1.0),
                'sample_titles': news_titles[:3]
            }

        except Exception as e:
            return {'error': str(e), 'sentiment_score': 0, 'confidence': 0}
    
    def _get_stock_forum_sentiment(self, ticker: str, days: int) -> Dict:
        """获取股票论坛讨论情绪"""
        # 由于东方财富股吧等平台的反爬虫机制，暂无法获取论坛数据
        # 返回置信度为 0 的空结果，不生成虚假数据
        return {
            'sentiment_score': 0,
            'discussion_count': 0,
            'hot_topics': [],
            'note': '股票论坛数据暂不可用，综合分析时不参考此维度',
            'confidence': 0
        }
    
    def _get_media_coverage_sentiment(self, ticker: str, days: int) -> Dict:
        """获取媒体报道情绪"""
        try:
            # 可以集成RSS源或公开的财经API
            coverage_items = self._get_media_coverage(ticker, days)
            
            if not coverage_items:
                return {'sentiment_score': 0, 'coverage_count': 0, 'confidence': 0}
            
            # 分析媒体报道的情绪倾向
            sentiment_scores = []
            for item in coverage_items:
                score = self._analyze_text_sentiment(item.get('title', '') + ' ' + item.get('summary', ''))
                sentiment_scores.append(score)
            
            avg_sentiment = sum(sentiment_scores) / len(sentiment_scores) if sentiment_scores else 0
            
            return {
                'sentiment_score': avg_sentiment,
                'coverage_count': len(coverage_items),
                'confidence': min(len(coverage_items) / 5, 1.0)
            }
            
        except Exception as e:
            return {'error': str(e), 'sentiment_score': 0, 'confidence': 0}
    
    def _search_finance_news(self, search_term: str, days: int) -> List[Dict]:
        """搜索财经新闻"""
        # 暂无可用的中文新闻搜索 API，返回空列表
        # 实际新闻数据由 realtime_news.py 中的新闻聚合器提供
        return []
    
    def _get_media_coverage(self, ticker: str, days: int) -> List[Dict]:
        """获取媒体报道 (示例实现)"""
        # 可以集成Google News API或其他新闻聚合服务
        return []
    
    def _analyze_text_sentiment(self, text: str) -> float:
        """简单的中文文本情绪分析"""
        if not text:
            return 0
        
        # 简单的关键词情绪分析
        positive_words = ['上涨', '增长', '利好', '看好', '买入', '推荐', '强势', '突破', '创新高']
        negative_words = ['下跌', '下降', '利空', '看空', '卖出', '风险', '跌破', '创新低', '亏损']
        
        positive_count = sum(1 for word in positive_words if word in text)
        negative_count = sum(1 for word in negative_words if word in text)
        
        if positive_count + negative_count == 0:
            return 0
        
        return (positive_count - negative_count) / (positive_count + negative_count)
    
    def _get_company_chinese_name(self, ticker: str) -> Optional[str]:
        """从数据库获取公司中文名称，用于增强新闻搜索关键词"""
        try:
            from app.core.database import get_database
            import asyncio

            db = get_database()

            async def _lookup():
                # 尝试按 symbol 字段查找（A股）
                doc = await db.stock_basics.find_one(
                    {"$or": [{"symbol": ticker}, {"ts_code": ticker}]},
                    {"name": 1}
                )
                if doc:
                    return doc.get("name")
                return None

            try:
                loop = asyncio.get_event_loop()
                if loop.is_running():
                    # 在已有事件循环中无法 run_until_complete，尝试 create_task
                    import concurrent.futures
                    with concurrent.futures.ThreadPoolExecutor() as pool:
                        future = pool.submit(asyncio.run, _lookup())
                        return future.result(timeout=5)
                return loop.run_until_complete(_lookup())
            except RuntimeError:
                try:
                    return asyncio.run(_lookup())
                except Exception:
                    return None
        except Exception:
            return None
    
    def _calculate_overall_sentiment(self, news_sentiment: Dict, forum_sentiment: Dict, media_sentiment: Dict) -> Dict:
        """计算综合情绪分析"""
        # 根据各数据源的置信度加权计算
        news_weight = news_sentiment.get('confidence', 0)
        forum_weight = forum_sentiment.get('confidence', 0)
        media_weight = media_sentiment.get('confidence', 0)
        
        total_weight = news_weight + forum_weight + media_weight
        
        if total_weight == 0:
            return {'sentiment_score': 0, 'confidence': 0, 'level': 'neutral'}
        
        weighted_sentiment = (
            news_sentiment.get('sentiment_score', 0) * news_weight +
            forum_sentiment.get('sentiment_score', 0) * forum_weight +
            media_sentiment.get('sentiment_score', 0) * media_weight
        ) / total_weight
        
        # 确定情绪等级
        if weighted_sentiment > 0.3:
            level = 'very_positive'
        elif weighted_sentiment > 0.1:
            level = 'positive'
        elif weighted_sentiment > -0.1:
            level = 'neutral'
        elif weighted_sentiment > -0.3:
            level = 'negative'
        else:
            level = 'very_negative'
        
        return {
            'sentiment_score': weighted_sentiment,
            'confidence': total_weight / 3,  # 平均置信度
            'level': level
        }
    
    def _generate_sentiment_summary(self, overall_sentiment: Dict) -> str:
        """生成情绪分析摘要"""
        level = overall_sentiment.get('level', 'neutral')
        score = overall_sentiment.get('sentiment_score', 0)
        confidence = overall_sentiment.get('confidence', 0)
        
        level_descriptions = {
            'very_positive': '非常积极',
            'positive': '积极',
            'neutral': '中性',
            'negative': '消极',
            'very_negative': '非常消极'
        }
        
        description = level_descriptions.get(level, '中性')
        confidence_level = '高' if confidence > 0.7 else '中' if confidence > 0.3 else '低'
        
        return f"市场情绪: {description} (评分: {score:.2f}, 置信度: {confidence_level})"


def get_chinese_social_sentiment(ticker: str, curr_date: str) -> str:
    """
    获取中国市场情绪分析的主要接口函数
    整合实时新闻聚合器的真实新闻数据
    """
    aggregator = ChineseFinanceDataAggregator()

    try:
        # 获取情绪分析数据
        sentiment_data = aggregator.get_stock_sentiment_summary(ticker, days=7)

        # 格式化输出
        if 'error' in sentiment_data:
            return f"""
中国市场情绪分析报告 - {ticker}
分析日期: {curr_date}

⚠️ 数据获取限制说明:
{sentiment_data.get('fallback_message', '数据获取遇到技术限制')}

建议:
1. 重点关注财经新闻和基本面分析
2. 参考官方财报和业绩指导
3. 关注行业政策和监管动态
4. 考虑国际市场情绪对中概股的影响

注: 由于数据源限制，当前主要依赖公开财经数据源进行分析。
"""

        overall = sentiment_data.get('overall_sentiment', {})
        news = sentiment_data.get('news_sentiment', {})
        confidence = overall.get('confidence', 0)
        confidence_level = '高' if confidence > 0.7 else '中' if confidence > 0.3 else '低'

        # 构建新闻标题展示
        sample_titles = news.get('sample_titles', [])
        news_sample_section = ""
        if sample_titles:
            news_sample_section = "\n📰 近期相关新闻:\n" + "\n".join(
                f"  - {title}" for title in sample_titles
            )

        return f"""
中国市场情绪分析报告 - {ticker}
分析日期: {curr_date}
分析周期: {sentiment_data.get('analysis_period', '7天')}
置信度: {confidence_level}
{news_sample_section}

📊 综合情绪评估:
{sentiment_data.get('summary', '数据不足')}

📰 财经新闻情绪:
- 情绪评分: {news.get('sentiment_score', 0):.2f}
- 正面新闻比例: {news.get('positive_ratio', 0):.1%}
- 负面新闻比例: {news.get('negative_ratio', 0):.1%}
- 新闻数量: {news.get('news_count', 0)}条

生成时间: {sentiment_data.get('timestamp', format_iso(now_utc()))}
"""

    except Exception as e:
        return f"""
中国市场情绪分析 - {ticker}
分析日期: {curr_date}

❌ 分析失败: {str(e)}

建议:
1. 查看财经新闻网站的相关报道
2. 关注东方财富等投资社区讨论
3. 参考专业机构的研究报告
4. 重点分析基本面和技术面数据
"""
        
    except Exception as e:
        return f"""
中国市场情绪分析 - {ticker}
分析日期: {curr_date}

❌ 分析失败: {str(e)}

💡 替代建议:
1. 查看财经新闻网站的相关报道
2. 关注雪球、东方财富等投资社区讨论
3. 参考专业机构的研究报告
4. 重点分析基本面和技术面数据

注: 中国社交媒体数据获取存在技术限制，建议以基本面分析为主。
"""
