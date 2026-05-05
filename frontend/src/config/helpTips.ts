export type HelpTip = {
  title?: string
  content: string
  examples?: string[]
}

export const helpTips = {
  stockSearch: {
    title: '股票搜索',
    content: '输入股票名称或代码，快速切换当前分析股票。切换后，交易剧本、预测图表、复盘和专业数据都会同步更新。',
  },
  stockPoolTags: {
    title: '自选股票池',
    content: '这里展示你当前关注的股票。点击任意股票标签，可以快速切换到该股票的交易剧本。',
  },
  currentSelectedStock: {
    title: '当前选中股票',
    content: '这里显示当前正在查看的股票。切换股票后，交易剧本、预测图表、复盘和专业数据都会同步更新。',
  },
  stockSearchResultView: {
    title: '查看匹配股票',
    content: '切换到搜索结果中的股票，并同步刷新交易剧本、预测图表、复盘和专业数据。',
  },
  stockSearchResultPin: {
    title: '置顶搜索结果',
    content: '把搜索到的股票加入并置顶到首页股票池，方便后续快速切换和参与明日操作清单。',
  },
  closeDialog: {
    title: '关闭窗口',
    content: '关闭当前弹窗或抽屉，不会删除数据，也不会改变当前交易计划。',
  },
  selectedStockStatus: {
    title: '当前股票状态条',
    content: '滚动页面时用来确认当前正在查看哪只股票，以及关键买入、止损、目标和仓位计划。',
  },
  tomorrowActionList: {
    title: '明日操作清单',
    content: '这里把股票按明天的操作方式分类，例如立即执行、等回调、等突破、建议减仓或规避。普通用户优先看这里即可。',
  },
  headerSearch: {
    title: '顶部搜索',
    content: '用于快速输入股票代码或简称。当前版本主要作为全局入口提示，首页请优先使用股票池控制器完成切换。',
  },
  timeRange: {
    title: '时间区间',
    content: '切换图表展示的历史范围。短线用户通常先看 5日/1月，复盘模型稳定性时再看更长周期。',
  },
  realtimeDataStatus: {
    title: '实时数据状态',
    content: '表示前端正在连接本地行情和分析接口。若数据长时间不更新，可以先刷新页面或查看数据管道诊断。',
  },
  notificationCenter: {
    title: '通知中心',
    content: '用于查看任务完成、数据异常或风险提醒。当前页面不会自动下单，通知只帮助你及时复核系统状态。',
  },
  marketIndices: {
    title: '主要市场指数',
    content: '展示上证、深证、创业板等大盘状态。普通用户可用它判断当日市场环境偏强还是偏弱，再决定是否降低仓位。',
  },
  executableNow: {
    title: '立即可执行',
    content: '表示当前价格或条件已经接近系统计划，可以按计划小仓操作。但仍需要遵守止损和仓位限制。',
  },
  waitForPullback: {
    title: '等回调低吸',
    content: '表示股票有机会，但当前价格不够理想。需要等价格回落到系统给出的买入区间，再考虑小仓。',
  },
  waitForBreakout: {
    title: '等突破确认',
    content: '表示目前还不能买，需要等价格突破关键价位并确认强势后，再考虑跟随。',
  },
  holdWatch: {
    title: '持有观察',
    content: '表示当前还不适合新增动作，已有持仓按计划价和止损线观察，未持有则等待更明确条件。',
  },
  reduceOrSell: {
    title: '建议减仓/卖出',
    content: '表示当前风险收益比变差，若已经持有，系统建议考虑降低仓位或按计划卖出。',
  },
  avoid: {
    title: '建议规避',
    content: '表示当前风险不可控、数据不支持或模型信心不足。普通用户不建议参与。',
  },
  tomorrowReviewSummary: {
    title: '昨日计划复盘',
    content: '检查上一交易日计划是否触发、是否达到目标价或止损价，用来判断系统规则是否需要调整。',
  },
  riskReminder: {
    title: '风险提醒',
    content: '汇总明日交易前需要优先注意的风险。普通用户应先看风险提醒，再看买入或持有理由。',
  },
  currentPlaybook: {
    title: '当前股票交易剧本',
    content: '这里把当前股票的买入条件、卖出条件、止损线、仓位和不同走势应对浓缩成可执行计划。',
  },
  currentConclusion: {
    title: '当前结论',
    content: '系统把价格、资金、预测、新闻和风险合并后的短线动作建议。它是辅助判断，不代表必须买卖。',
  },
  currentPrice: {
    title: '当前价格',
    content: '最近可用行情价格，用来判断是否接近买入区、止损线或目标价。行情可能存在延迟，请以实际交易软件为准。',
  },
  idealBuyRange: {
    title: '理想买入区间',
    content: '系统认为相对更合适的买入价格范围。价格进入该区间后，还需要结合成交量和风险条件判断。',
  },
  breakoutBuyAbove: {
    title: '突破买入价',
    content: '如果价格放量突破这个位置，说明短线强度可能增强，可以作为突破型买入条件之一。',
  },
  doNotChaseAbove: {
    title: '不建议追高价',
    content: '如果价格高于这个位置，短线风险会明显增加，普通用户不建议追高买入。',
  },
  stopLossPrice: {
    title: '止损价',
    content: '如果买入后价格跌破这个位置，说明原交易计划可能失效，应考虑止损或降低仓位。',
  },
  takeProfitPrice1: {
    title: '第一目标价',
    content: '系统给出的第一阶段止盈参考价。到达后可以考虑卖出一部分，锁定收益。',
  },
  takeProfitPrice2: {
    title: '第二目标价',
    content: '系统给出的更高目标价。适合在走势继续强势时作为进一步止盈参考。',
  },
  suggestedPosition: {
    title: '建议仓位',
    content: '系统根据风险、置信度和波动情况给出的仓位建议。风险越高，建议仓位越低。',
  },
  confidence: {
    title: '系统信心',
    content: '表示系统对当前交易剧本的把握程度。信心低时，不建议重仓或激进操作。',
  },
  riskLevel: {
    title: '风险等级',
    content: '表示当前交易的不确定性和潜在亏损风险。风险高不代表一定不能买，但必须降低仓位并严格止损。',
  },
  targetHorizon: {
    title: '适合周期',
    content: '系统当前剧本主要参考的短线周期，例如 D5 表示偏 5 个交易日观察。周期越短，越需要严格执行条件和止损。',
  },
  riskRewardRatio: {
    title: '风险收益比',
    content: '用预期上涨空间和可能下跌空间做对比。数值越高越有参考价值，但不能当作收益承诺。',
  },
  planInvalidation: {
    title: '计划失效条件',
    content: '当价格跌破止损、模型信心下降，或新闻/资金面明显转弱时，本次计划应停止使用并重新评估。',
  },
  buyConditions: {
    title: '买入条件',
    content: '只有满足这些价格、成交量或确认条件时，才考虑按计划小仓执行。没有触发条件时，不建议提前行动。',
  },
  cancelBuyConditions: {
    title: '取消买入',
    content: '这些情况出现时，说明原本的买入计划风险变大，应放弃本次买入或等待系统重新生成计划。',
  },
  sellConditions: {
    title: '卖出/止盈/止损',
    content: '说明持有后如何分批止盈、何时降低仓位，以及跌破哪个位置需要执行风控。',
  },
  riskControlRules: {
    title: '风险控制',
    content: '这里列出仓位上限、止损线、不追高等约束。普通用户应先看风险控制，再看买入理由。',
  },
  scenarioOverview: {
    title: '明日情景剧本',
    content: '把明天可能出现的高开、低开、回调、突破、跌破和横盘分别写成应对动作，避免盘中临时冲动决策。',
  },
  scenarioGapUp: {
    title: '如果高开',
    content: '用于判断开盘价明显高于昨日收盘时是否还能参与。若已超过不追高价，普通用户应优先等待。',
  },
  scenarioGapDown: {
    title: '如果低开',
    content: '用于判断低开时是等待企稳还是取消计划。若低开后跌破止损线，原剧本通常应失效。',
  },
  scenarioPullback: {
    title: '如果回调',
    content: '用于判断价格回落时是否进入更合适的买入区。回调只是观察条件，还要看价格是否企稳。',
  },
  scenarioBreakout: {
    title: '如果突破',
    content: '用于判断价格上穿关键位置时是否可以小仓跟随。突破需要结合成交量和风险条件确认。',
  },
  scenarioBreakdown: {
    title: '如果跌破',
    content: '用于判断价格跌破关键支撑或止损线后的风控动作。跌破后不建议继续按原买入计划执行。',
  },
  scenarioSideways: {
    title: '如果横盘',
    content: '用于判断价格没有方向时是否继续等待。横盘阶段通常少操作，等买入区、突破或止损条件出现。',
  },
  ifNotHolding: {
    title: '如果未持有',
    content: '说明空仓用户应等待什么条件再行动，重点是避免没有触发价位时提前追入。',
  },
  ifAlreadyHolding: {
    title: '如果已持有',
    content: '说明已有仓位时如何观察、止盈或止损。已有持仓也需要遵守计划，不建议因为短线波动随意加仓。',
  },
  normalMode: {
    title: '普通模式',
    content: '为普通用户准备，只展示交易结论、买卖价位、风险控制和简单解释。',
  },
  professionalMode: {
    title: '专业模式',
    content: '展示更多技术指标、预测明细、历史复盘和原始数据，适合有投资经验的用户。',
  },
  predictionChart: {
    title: '预测图表',
    content: '图表展示历史价格、AI 预测走势、买入区间、止损线和目标价。普通用户重点看买入区、止损线和目标价。',
  },
  agentReason: {
    title: 'Agent 分析理由',
    content: '多个 AI Agent 会从技术面、资金面、新闻、宏观政策、企业实力和风险控制等角度共同分析。这里展示它们的主要结论。',
  },
  agentMacroPolicy: {
    title: '宏观政策分析',
    content: '观察政策、行业环境和大盘风险是否支持当前交易。宏观因素偏弱时，即使个股有机会也要更保守。',
  },
  agentCompanyFundamental: {
    title: '企业实力分析',
    content: '从公司基本面、行业位置和经营稳定性理解股票底层质量。短线交易也要避免忽视公司本身风险。',
  },
  agentNewsSentiment: {
    title: '新闻情绪分析',
    content: '观察近期新闻偏正面、负面还是中性。新闻情绪只是辅助线索，不能单独作为买卖依据。',
  },
  newsSentiment: {
    title: '新闻情绪',
    content: '新闻情绪用于辅助理解市场反应，不能单独作为买卖依据。遇到重大新闻时，还需要结合公告、价格和风险控制。',
  },
  agentCapitalFlow: {
    title: '资金流分析',
    content: '观察主力、大单等资金净流入或流出情况。资金流可能反复，适合与价格位置一起看。',
  },
  agentLargeMoney: {
    title: '疑似大资金行为',
    content: '用于提示可能存在的大额资金集中流入、流出或异动。这里只能说“疑似”或“可能”，不能判断一定有人为操纵。',
  },
  agentTechnicalTiming: {
    title: '技术买卖点分析',
    content: '从均线、动量、支撑压力和成交量判断短线时机。普通用户重点看是否接近计划价位。',
  },
  agentPriceForecast: {
    title: '短线价格预测',
    content: '根据模型预测未来几个交易日可能的价格区间。预测有误差，应配合止损线和仓位控制使用。',
  },
  agentRiskControl: {
    title: '风险控制分析',
    content: '检查当前计划是否存在高波动、数据不足、负面事件或止损空间过大的问题。风险项优先级高于买入理由。',
  },
  agentPlainExplain: {
    title: '普通用户解释',
    content: '把专业模型结论翻译成更容易执行的语言，帮助你知道该等、该看、还是该回避。',
  },
  tradeReview: {
    title: '交易复盘',
    content: '复盘用于检查昨天或前几天的交易计划是否触发、是否达到目标价、是否止损，以及下一次如何优化。',
  },
  dataDetails: {
    title: '数据详情',
    content: '逐日展示实际价格、模型预测、预测区间和复盘结果。普通用户主要看预测是否经常偏离实际，以及方向是否稳定。',
  },
  decisionSummary: {
    title: '一屏式决策摘要',
    content: '把当前股票的模型结论、置信度、预期收益、风险和数据健康压缩到一屏。普通用户先看这里，再决定是否展开细节。',
  },
  recommendationQueue: {
    title: '推荐队列',
    content: '按模型质量、风险和综合评分对自选股票排序。队列只帮助你优先查看，不代表排名靠前就一定适合买入。',
  },
  refreshSummary: {
    title: '刷新摘要',
    content: '重新拉取当前决策摘要和排序结果。刷新只更新页面数据，不会修改股票池，也不会执行交易。',
  },
  dataHealth: {
    title: '数据健康',
    content: '表示返回股票中有多少具备可用信号。健康度不足时，结论可能受行情、预测或新闻数据缺失影响。',
  },
  diagnosticButton: {
    title: '诊断',
    content: '打开当前股票的数据管道诊断，用于查看行情、预测、完整报告等后台任务是否正常。普通用户一般只在数据异常时查看。',
  },
  modelReviewSummary: {
    title: '模型复盘',
    content: '汇总模型近期预测表现、门禁状态和自动核实结果。它用于判断模型是否值得参考，不是单独买卖依据。',
  },
  dataGate: {
    title: '模型门禁',
    content: '用于限制样本不足、偏差较大或风险过高的信号进入候选。门禁未通过时，应优先观察或回避。',
  },
  verificationStatus: {
    title: '自动核实',
    content: '系统对模型结果做的基础校验，例如样本、方向、偏差和数据完整性。未通过时，需要谨慎使用结论。',
  },
  professionalData: {
    title: '专业数据',
    content: '这里包含完整技术指标、预测明细、资金流、历史数据和模型指标。普通用户不需要优先查看。',
  },
  modelStatus: {
    title: '模型状态',
    content: '用于检查当前股票的预测样本、历史误差、方向准确率、Agent 审核和数据管道状态。普通用户只需关注是否提示风险或样本不足。',
  },
  runTraining: {
    title: '运行训练',
    content: '触发后台训练或日常分析任务，刷新模型结果和复盘数据。该操作不会下单，也不代表交易建议。',
  },
  watchlistSnapshot: {
    title: '自选实时看板',
    content: '这里是完整自选股实时行情表，适合盘中巡检。它不再占据第一屏，避免干扰核心交易决策。',
  },
  refreshPlaybook: {
    title: '刷新交易剧本',
    content: '重新拉取当前股票的最新行情、预测、风险控制和 Agent 分析结果。',
  },
  refreshData: {
    title: '刷新数据',
    content: '重新请求当前页面数据，适合在任务刚完成或页面停留较久后使用。刷新不会改变股票池或交易计划。',
  },
  retryTask: {
    title: '立即重试',
    content: '重新触发当前股票的数据管道任务，适合行情、预测或完整报告失败时使用。普通用户通常先刷新页面，仍异常再重试。',
  },
  viewDetails: {
    title: '查看详情',
    content: '打开更完整的明细、日志或分析结果。普通用户只在需要排查数据或理解结论来源时查看。',
  },
  expandCollapse: {
    title: '展开/收起',
    content: '展开可查看明细，收起可减少页面干扰。核心决策优先看第一屏摘要即可。',
  },
  deleteStock: {
    title: '删除股票',
    content: '从股票池中移除这只股票。删除后它不会参与明日操作清单和首页交易剧本汇总。',
  },
  pinStock: {
    title: '置顶股票',
    content: '置顶后会优先出现在首页顶部股票标签中，方便快速切换查看。切换股票后，交易剧本、预测图表、复盘和专业数据都会同步更新。',
  },
  addStock: {
    title: '加入股票池',
    content: '把搜索到的股票加入关注列表。加入后可在首页选择，并参与明日操作清单和交易剧本生成。',
  },
  manageStockPool: {
    title: '管理股票池',
    content: '添加、删除或调整你关注的股票。股票池中的股票会参与明日操作清单和交易剧本生成。',
  },
  dataPipelineDiagnosis: {
    title: '数据管道诊断',
    content: '用于查看行情、预测、复盘等后台任务是否正常。普通用户一般不需要查看，适合排查系统数据问题。',
  },
  pipelineRunTime: {
    title: '执行时间',
    content: '任务开始运行的时间。用于判断数据是否为最近一次更新结果。',
  },
  pipelineRunType: {
    title: '任务类型',
    content: '说明本次后台任务属于行情补数、预测、信号计算还是完整报告。不同任务会影响页面不同区域。',
  },
  fullReportTask: {
    title: '完整报告',
    content: '后台生成价格、预测、技术指标和复盘所需的完整数据。若失败，专业数据页可能不完整。',
  },
  fetchDailyTask: {
    title: '行情补数',
    content: '检查并补齐股票日线行情。行情缺失时，预测图表、止损价和复盘都可能受到影响。',
  },
  predictionTask: {
    title: '预测任务',
    content: '后台生成短线价格预测和方向判断。预测结果只作辅助分析，不能替代交易纪律。',
  },
  copyError: {
    title: '复制错误',
    content: '复制本次任务的错误信息，便于排查数据源、预测任务或后台服务问题。',
  },
  copyLog: {
    title: '复制日志',
    content: '复制任务日志尾部，适合排查为什么行情、预测或完整报告没有正常生成。普通用户通常无需查看。',
  },
  triggerSource: {
    title: '触发源',
    content: '说明任务是由定时调度、手动刷新还是重试触发。用于排查为什么某次任务运行。',
  },
  duration: {
    title: '耗时',
    content: '任务从开始到结束花费的时间。耗时过长可能代表数据源慢、网络波动或后台压力较大。',
  },
  status: {
    title: '状态',
    content: '成功表示任务正常完成；失败表示需要查看错误；执行中表示仍在后台运行；跳过通常代表暂无必要重复计算。',
  },
  successFailure: {
    title: '成功/失败',
    content: '成功不代表股票一定可买，只代表数据任务完成；失败通常需要刷新、重试或查看日志。',
  },
  menuMarketOverview: {
    title: '市场总览',
    content: '查看明日操作清单、整体市场判断、重点股票和当前选中股票交易剧本。',
  },
  menuDeepAnalysis: {
    title: '深度分析',
    content: '查看更详细的个股分析、预测图表、Agent 理由和专业指标。',
  },
  menuStrategyCenter: {
    title: '策略中心',
    content: '查看短线策略、模拟交易、买卖计划和策略表现。',
  },
  menuIntelligence: {
    title: '情报监控',
    content: '查看新闻、政策、宏观、行业和个股情绪分析。',
  },
  menuDailyReview: {
    title: '每日复盘',
    content: '复盘昨天的交易计划是否有效、哪些判断正确、哪些需要优化。',
  },
  menuSettings: {
    title: '平台设置',
    content: '配置股票池、数据源、模型参数、页面模式和系统偏好。',
  },
  mape: {
    title: 'MAPE',
    content: '价格预测平均误差。数值越低，表示价格预测越接近实际。普通用户可以理解为模型最近价格预测准不准。',
  },
  directionAccuracy: {
    title: '方向准确率',
    content: '模型判断上涨或下跌方向的准确程度。方向准确率低时，不适合只根据单次预测重仓。',
  },
  intervalHitRate: {
    title: '区间命中率',
    content: '实际价格落入模型预测区间的比例。区间命中率高，说明模型对价格波动范围有一定参考价值。',
  },
  rsi: {
    title: 'RSI',
    content: '衡量股票短期强弱和是否过热的技术指标。数值过高可能代表短线过热，数值过低可能代表偏弱或超跌。',
  },
  macd: {
    title: 'MACD',
    content: '常用趋势指标，用于观察股票趋势强弱和可能的转折。普通用户不需要单独依赖它做决策。',
  },
  snr: {
    title: 'SNR',
    content: '方向信号相对噪声的强弱。数值越高，说明模型认为方向信号更清晰；数值低时要更谨慎。',
  },
  riskScore: {
    title: '风险评分',
    content: '系统把波动、回撤、新闻、资金和模型不确定性合成的风险分。分数越高，越应该降低仓位或回避。',
  },
  compositeScore: {
    title: '综合评分',
    content: '多个技术和模型指标的加权结果。它可以帮助排序，但不应单独决定买卖。',
  },
  upsideProbability: {
    title: '上涨概率',
    content: '模型估计短线方向偏上的概率。概率高不代表后续表现无风险，仍要结合价格位置、止损和仓位控制。',
  },
  aiTradeInsight: {
    title: 'AI 交易辅助建议',
    content: '把模型预测、资金、情绪、技术指标和风险控制合并成辅助结论。它不会自动下单，也不构成投资建议。',
  },
  pricePlan: {
    title: '价格计划',
    content: '展示买入区、不追高价、止损价、目标价和建议仓位。普通用户应严格按条件执行，不要把参考价当作保证价。',
  },
  explainabilityDetails: {
    title: '可解释性详情',
    content: '展开后查看哪些因子对模型结论贡献较大。它帮助理解模型为什么这样判断，但不能替代独立判断。',
  },
  factorScores: {
    title: '多维因子评分',
    content: '把方向概率、预期收益、风险惩罚、动量、资金流、情绪面和技术面分开展示，便于看清结论来源。',
  },
  featureImportance: {
    title: '特征贡献度',
    content: '显示模型最依赖的输入特征。贡献度高只说明影响模型判断较大，不代表该因素一定会驱动股价。',
  },
  inputCoverage: {
    title: '输入覆盖率',
    content: '表示本次模型判断所需数据是否齐全。覆盖率低时，结论可信度会下降。',
  },
  featureSnapshot: {
    title: '复盘快照',
    content: '记录模型当时使用的数据、目标日期和覆盖情况，用于之后复盘预测是否可靠。',
  },
  factorContext: {
    title: '因子上下文',
    content: '展示新闻、市场广度和量化因子的背景信息，帮助理解模型结论所处环境。',
  },
  marketBreadth: {
    title: '市场广度',
    content: '观察市场中上涨股票的覆盖程度。广度偏弱时，即使个股信号较好也要控制仓位。',
  },
  newsCount: {
    title: '新闻数量',
    content: '表示近几日可用于分析的新闻条数。新闻少时，情绪结论可能不稳定。',
  },
  mainNetInflow: {
    title: '主力净流入',
    content: '统计大额资金净买入金额。净流入说明资金可能更积极，但并不代表价格会持续走强。',
  },
  mainNetOutflow: {
    title: '主力净流出',
    content: '统计大额资金净卖出金额。净流出说明资金可能偏谨慎，需要结合价格位置和成交量判断。',
  },
  mainNetRatio: {
    title: '净占比',
    content: '主力净流入或净流出占成交额的比例。比例越高，说明资金动作相对更明显。',
  },
  turnoverRate: {
    title: '换手率',
    content: '表示股票当天成交活跃程度。换手过高可能意味着分歧变大，短线风险也可能升高。',
  },
  volumeRatio: {
    title: '量比',
    content: '当前成交量相对平时的放大程度。量比高说明交易更活跃，但要区分放量上涨还是放量下跌。',
  },
  amount: {
    title: '成交额',
    content: '当天成交金额，反映资金参与规模。成交额太小的股票可能流动性不足，买卖不容易。',
  },
  volume: {
    title: '成交量',
    content: '当天成交股数，用于观察市场活跃度。突然放量需要结合涨跌方向和位置判断。',
  },
  peRatio: {
    title: '市盈率',
    content: '股价相对盈利能力的估值指标。市盈率高不一定不好，但代表市场对未来预期更高。',
  },
  pbRatio: {
    title: '市净率',
    content: '股价相对净资产的估值指标。适合辅助观察估值高低，但不适合单独做短线决策。',
  },
  priceOverview: {
    title: '价格概览',
    content: '展示收盘价、涨跌幅和成交量。普通用户可用它确认当前价格位置和市场活跃度，但仍需以交易软件实时行情为准。',
  },
  movingAverage: {
    title: '均线',
    content: '把一段时间内的收盘价取平均形成趋势线。短期均线强于长期均线说明近期走势偏强，但仍需结合成交量和风险位。',
  },
  technicalAction: {
    title: '操作建议',
    content: '由技术评分自动生成的辅助标签。它只反映技术面倾向，不等同于买卖指令。',
  },
  predictionSignal: {
    title: '下一交易日预测信号',
    content: '展示模型对下一交易日方向、价格和区间的判断。预测存在误差，应与止损线和仓位控制一起使用。',
  },
  dataQuality: {
    title: '数据质量',
    content: '衡量行情、指标和预测输入是否完整。数据质量低时，结论需要降低权重。',
  },
  predictionConfidence: {
    title: '预测置信度',
    content: '表示模型对本次预测的把握程度。置信度低时，应优先观察，不适合激进操作。',
  },
  forecastReturn: {
    title: '预测收益率',
    content: '模型预测价格相对当前价格的变化幅度。它是概率性参考，不是收益承诺。',
  },
  downsideRisk: {
    title: '下行风险',
    content: '如果走势不利，模型估计可能承受的下跌空间。下行风险大时应降低仓位或不参与。',
  },
  upsidePotential: {
    title: '预期上涨空间',
    content: '模型估计的潜在上涨幅度。需要同时比较止损距离和风险等级，不能只看上涨空间。',
  },
  historicalPrice: {
    title: '历史价格',
    content: '过去实际收盘价，用来观察趋势、支撑压力和预测是否偏离现实走势。',
  },
  aiPredictionLine: {
    title: 'AI 预测主线',
    content: '模型给出的未来价格中心线。它可能偏离实际走势，必须配合预测区间和止损线使用。',
  },
  predictionUpper: {
    title: '预测上界',
    content: '模型认为较乐观情况下可能到达的价格上沿。不是目标价，也不是保证价格。',
  },
  predictionLower: {
    title: '预测下界',
    content: '模型认为较保守情况下可能到达的价格下沿。若价格接近下界，需重点看止损和风险。',
  },
  historicalPrediction: {
    title: '历史预测',
    content: '过去某天模型曾经给出的预测，用于和实际走势对比，判断模型近期是否可靠。',
  },
  actualClose: {
    title: '实际收盘价',
    content: '交易日最终收盘价格，是复盘模型预测是否命中的基准。',
  },
  yesterdayPlan: {
    title: '昨日计划',
    content: '昨天系统给出的计划，用来检查今天是否按条件触发，以及计划是否仍然有效。',
  },
  buyTriggered: {
    title: '是否触发买入',
    content: '复盘价格是否进入买入区或突破确认价。触发买入不代表后续必然获利，还要看执行和风控。',
  },
  targetReached: {
    title: '是否达到目标价',
    content: '检查价格是否到达系统给出的止盈参考位。达到目标后通常考虑分批止盈或上移止损。',
  },
  stopLossTriggered: {
    title: '是否触发止损',
    content: '检查价格是否跌破止损线。触发止损说明原计划可能失效，应优先控制风险。',
  },
  planValid: {
    title: '计划是否有效',
    content: '复盘原计划的触发条件和风险控制是否仍成立。无效计划应停止使用并等待新剧本。',
  },
  failureReason: {
    title: '失败原因',
    content: '当预测或计划偏差较大时，这里说明可能原因，例如行情突变、新闻冲击、资金反向或样本不足。',
  },
  nextOptimization: {
    title: '下次优化建议',
    content: '根据复盘结果给出下一轮模型或交易规则的改进方向。它用于改进系统，不是直接买卖指令。',
  },
  hardRefresh: {
    title: '硬刷新',
    content: '绕过数据库缓存，直接读取最新落盘文件。适合排查报告不同步，普通用户通常用普通刷新即可。',
  },
  ensureNewsCounts: {
    title: '校验并补齐新闻数',
    content: '逐只股票检查新闻数量，不足时尝试补采。用于保证 Agent 分析有足够新闻材料。',
  },
  retailDecisionCard: {
    title: '普通用户决策卡',
    content: '把专业模型结果翻译成是否等待、是否小仓、如何止损和何时放弃计划。它只作辅助分析，不构成投资建议。',
  },
  retailActionBuy: {
    title: '可以买入',
    content: '表示价格和风险条件相对接近计划，但仍建议小仓、分批，并严格遵守止损。',
  },
  retailActionWatch: {
    title: '小仓观察',
    content: '表示股票有一定机会，但信号还不够强或价格不够理想。普通用户可以加入观察，不必急着操作。',
  },
  retailActionSell: {
    title: '建议卖出/减仓',
    content: '表示当前风险或价格位置不再理想。已有持仓可考虑降低仓位或按计划卖出，未持有不建议追入。',
  },
  retailActionAvoid: {
    title: '建议规避',
    content: '表示风险、数据质量或模型信心不支持参与。普通用户应优先保留现金或等待新机会。',
  },
  generateAgentReport: {
    title: '生成报告',
    content: '启动一次 Agent 分析任务，生成自选/股票池摘要、新闻解释和风险提示。生成过程不会下单。',
  },
  backfillHistory: {
    title: '回填历史',
    content: '补采过去一段时间的股票新闻和画像材料，用于完善新闻分析和 Agent 报告。该操作只更新数据，不代表交易建议。',
  },
  dashboardReports: {
    title: '报告页',
    content: '查看系统生成的分析报告和任务结果，适合确认数据是否已经产出。',
  },
  dashboardStats: {
    title: '统计页',
    content: '查看后台任务、预测数量和运行状态。主要用于系统维护，不是交易决策入口。',
  },
  dashboardMacro: {
    title: '宏观页',
    content: '查看宏观环境、政策和市场风险。大盘偏弱时，即使个股剧本较好也应控制仓位。',
  },
  dashboardAgent: {
    title: 'Agent 页',
    content: '查看 AI Agent 生成的日报和解释链路，帮助理解系统为什么给出当前判断。',
  },
} satisfies Record<string, HelpTip>

export type HelpTipKey = keyof typeof helpTips