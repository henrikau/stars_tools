#include "ns3/command-line.h"
#include "ns3/bgp.h"
#include "ns3/core-module.h"
#include "ns3/csma-module.h"
#include "ns3/internet-module.h"
#include "ns3/network-module.h"

#include <boost/property_tree/json_parser.hpp>
#include <boost/property_tree/ptree.hpp>

#include <algorithm>
#include <cctype>
#include <cstdlib>
#include <cstdint>
#include <fstream>
#include <iomanip>
#include <iostream>
#include <map>
#include <memory>
#include <sstream>
#include <stdexcept>
#include <string>
#include <vector>

using namespace ns3;

namespace
{

struct LanConfig
{
    std::string id;
    std::string prefix;
    std::string capacity;
    std::string delay;
};

struct AsConfig
{
    std::string id;
    uint32_t asn = 0;
    std::string routerId;
    std::string bgpRouterId;
    std::vector<LanConfig> lans;
};

struct LinkConfig
{
    std::string id;
    std::string asA;
    std::string asB;
    std::string capacity;
    std::string delay;
    int32_t initialBgpWeight = 0;
};

struct OriginPrefixConfig
{
    std::string id;
    std::string originAs;
    std::string prefix;
    std::string lanId;
};

struct LinkRuntime
{
    LinkConfig config;
    NetDeviceContainer devices;
    Ipv4InterfaceContainer interfaces;
    Ptr<CsmaChannel> channel;
    std::string subnet;
    Ipv4Address addressA;
    Ipv4Address addressB;
    uint32_t asnA = 0;
    uint32_t asnB = 0;
    bool aInitiates = false;
};

struct LanRuntime
{
    std::string asId;
    LanConfig config;
    Ptr<Node> host;
    NetDeviceContainer devices;
    Ipv4InterfaceContainer interfaces;
};

struct Topology
{
    std::vector<AsConfig> ases;
    std::vector<LinkConfig> links;
    std::vector<OriginPrefixConfig> originPrefixes;
};

struct BgpWeightEvent
{
    std::string id;
    double time = 0.0;
    std::string from;
    std::string to;
    std::string linkId;
    int32_t weight = 0;
    bool active = true;
    std::string label;
    uint32_t fileOrder = 0;
};

struct ScheduleConfig
{
    std::vector<BgpWeightEvent> bgpWeightEvents;
    double lastEventTime = 0.0;
};

struct BgpRuntime
{
    std::map<std::string, Ptr<Bgp>> apps;
    std::map<std::string, Ipv4Address> peerAddress;
    std::map<std::string, bool> peerPassive;
};

struct ScheduledBgpWeightAction
{
    BgpWeightEvent event;
    Ptr<Bgp> localBgp;
    Ipv4Address peerAddress;
    Ptr<Bgp> remoteBgp;
    Ipv4Address reversePeerAddress;
    bool localPeerPassive = false;
    bool remotePeerPassive = false;
    bool allowPeerReset = false;
    bool forcePeerReset = false;
    std::string localRouterId;
    uint32_t localAsn = 0;
};

class EventCsvLogger
{
  public:
    EventCsvLogger(const std::string& path, const std::map<std::string, uint32_t>& asnByRouterId)
        : m_path(path),
          m_asnByRouterId(asnByRouterId)
    {
        m_stream.open(path.c_str(), std::ios::out | std::ios::trunc);
        if (!m_stream.is_open())
        {
            throw std::runtime_error("Failed to open BGP trace CSV: " + path);
        }

        m_stream << "simulated_time,router_id,asn,event_type,prefix,nexthop,as_path,peer,source_context\n";
        m_stream.flush();
    }

    void LogEvent(double simulatedTime,
                  const std::string& routerId,
                  uint32_t asn,
                  const std::string& eventType,
                  const std::string& prefix,
                  const std::string& nexthop,
                  const std::string& asPath,
                  const std::string& peer,
                  const std::string& sourceContext)
    {
        m_stream << std::fixed << std::setprecision(6) << simulatedTime << ','
                 << CsvCell(routerId) << ','
                 << asn << ','
                 << CsvCell(eventType) << ','
                 << CsvCell(prefix) << ','
                 << CsvCell(nexthop) << ','
                 << CsvCell(asPath) << ','
                 << CsvCell(peer) << ','
                 << CsvCell(sourceContext) << '\n';
    }

    uint32_t LookupAsn(const std::string& routerId) const
    {
        auto it = m_asnByRouterId.find(routerId);
        if (it == m_asnByRouterId.end())
        {
            return 0;
        }
        return it->second;
    }

    const std::string& Path() const
    {
        return m_path;
    }

    void Flush()
    {
        m_stream.flush();
    }

  private:
    static std::string CsvCell(const std::string& value)
    {
        if (value.find(',') == std::string::npos &&
            value.find('"') == std::string::npos &&
            value.find('\n') == std::string::npos)
        {
            return value;
        }

        std::string escaped;
        escaped.reserve(value.size() + 2);
        escaped.push_back('"');
        for (char c : value)
        {
            if (c == '"')
            {
                escaped.push_back('"');
            }
            escaped.push_back(c);
        }
        escaped.push_back('"');
        return escaped;
    }

    std::string m_path;
    std::ofstream m_stream;
    std::map<std::string, uint32_t> m_asnByRouterId;
};

std::shared_ptr<EventCsvLogger> g_eventLogger;

std::string
Ipv4ToString(const Ipv4Address& address)
{
    std::ostringstream os;
    os << address;
    return os.str();
}

void
OnBgpRouteEvent(std::string routerId,
                std::string eventType,
                uint32_t prefix,
                uint8_t prefixLength,
                uint32_t nexthop,
                std::string asPath)
{
    if (!g_eventLogger)
    {
        return;
    }

    std::ostringstream prefixText;
    prefixText << Ipv4Address(prefix) << "/" << static_cast<uint32_t>(prefixLength);

    std::string nexthopText;
    if (nexthop != 0)
    {
        nexthopText = Ipv4ToString(Ipv4Address(nexthop));
    }

    g_eventLogger->LogEvent(Simulator::Now().GetSeconds(),
                            routerId,
                            g_eventLogger->LookupAsn(routerId),
                            eventType,
                            prefixText.str(),
                            nexthopText,
                            asPath,
                            "",
                            "bgp_route_event");
}

uint32_t
AsNumberFromId(const std::string& asId)
{
    if (asId.size() < 3 || asId[0] != 'a' || asId[1] != 's')
    {
        throw std::runtime_error("AS ID must use form asN: " + asId);
    }

    uint32_t value = 0;
    for (size_t i = 2; i < asId.size(); ++i)
    {
        if (!std::isdigit(static_cast<unsigned char>(asId[i])))
        {
            throw std::runtime_error("AS ID must use numeric suffix: " + asId);
        }
        value = value * 10 + static_cast<uint32_t>(asId[i] - '0');
    }
    return value;
}

std::string
SubnetForLink(const std::string& asA, const std::string& asB)
{
    uint32_t a = AsNumberFromId(asA);
    uint32_t b = AsNumberFromId(asB);
    uint32_t lo = std::min(a, b);
    uint32_t hi = std::max(a, b);

    std::ostringstream os;
    os << "10." << lo << "." << hi << ".0";
    return os.str();
}

Ipv4Address
AddressForLinkEndpoint(const std::string& endpoint, const std::string& other)
{
    uint32_t self = AsNumberFromId(endpoint);
    uint32_t peer = AsNumberFromId(other);
    uint32_t lo = std::min(self, peer);
    uint32_t hi = std::max(self, peer);
    uint32_t host = (self == lo) ? 1 : 2;

    std::ostringstream os;
    os << "10." << lo << "." << hi << "." << host;
    return Ipv4Address(os.str().c_str());
}

std::string
NetworkAddressFromPrefix(const std::string& prefix)
{
    size_t slash = prefix.find('/');
    if (slash == std::string::npos)
    {
        return prefix;
    }
    return prefix.substr(0, slash);
}

Ipv4Mask
MaskFromPrefix(const std::string& prefix)
{
    size_t slash = prefix.find('/');
    if (slash == std::string::npos)
    {
        throw std::runtime_error("Prefix is missing mask length: " + prefix);
    }

    uint32_t length = static_cast<uint32_t>(std::stoul(prefix.substr(slash + 1)));
    if (length > 32)
    {
        throw std::runtime_error("Invalid IPv4 prefix length: " + prefix);
    }

    uint32_t mask = (length == 0) ? 0 : (0xffffffffu << (32 - length));
    return Ipv4Mask(mask);
}

Ipv4Address
LanAddress(const std::string& prefix, uint32_t host)
{
    Ipv4Address network(NetworkAddressFromPrefix(prefix).c_str());
    uint32_t address = network.Get() + host;
    return Ipv4Address(address);
}

uint32_t
PrefixLengthFromPrefix(const std::string& prefix)
{
    size_t slash = prefix.find('/');
    if (slash == std::string::npos)
    {
        throw std::runtime_error("Prefix is missing mask length: " + prefix);
    }
    return static_cast<uint32_t>(std::stoul(prefix.substr(slash + 1)));
}

std::string
DirectedPeerKey(const std::string& from, const std::string& to, const std::string& linkId)
{
    return from + "->" + to + "@" + linkId;
}

std::string
ReverseDirectedPeerKey(const BgpWeightEvent& event)
{
    return DirectedPeerKey(event.to, event.from, event.linkId);
}

Topology
LoadTopology(const std::string& path)
{
    namespace pt = boost::property_tree;

    pt::ptree root;
    pt::read_json(path, root);

    Topology topology;

    for (const auto& asEntry : root.get_child("ases"))
    {
        const pt::ptree& node = asEntry.second;
        AsConfig as;
        as.id = node.get<std::string>("id");
        as.asn = node.get<uint32_t>("asn");
        as.routerId = node.get<std::string>("router_id");
        as.bgpRouterId = node.get<std::string>("bgp_router_id");

        if (auto lans = node.get_child_optional("lan_prefixes"))
        {
            for (const auto& lanEntry : *lans)
            {
                const pt::ptree& lanNode = lanEntry.second;
                LanConfig lan;
                lan.id = lanNode.get<std::string>("id");
                lan.prefix = lanNode.get<std::string>("prefix");
                lan.capacity = lanNode.get<std::string>("capacity");
                lan.delay = lanNode.get<std::string>("delay");
                as.lans.push_back(lan);
            }
        }

        topology.ases.push_back(as);
    }

    for (const auto& linkEntry : root.get_child("links"))
    {
        const pt::ptree& node = linkEntry.second;
        LinkConfig link;
        link.id = node.get<std::string>("id");
        link.capacity = node.get<std::string>("capacity");
        link.delay = node.get<std::string>("delay");
        link.initialBgpWeight = node.get<int32_t>("initial_bgp_weight");

        std::vector<std::string> endpoints;
        for (const auto& endpoint : node.get_child("endpoints"))
        {
            endpoints.push_back(endpoint.second.get_value<std::string>());
        }
        if (endpoints.size() != 2)
        {
            throw std::runtime_error("Link must have exactly two endpoints: " + link.id);
        }
        link.asA = endpoints[0];
        link.asB = endpoints[1];
        topology.links.push_back(link);
    }

    for (const auto& prefixEntry : root.get_child("origin_prefixes"))
    {
        const pt::ptree& node = prefixEntry.second;
        OriginPrefixConfig prefix;
        prefix.id = node.get<std::string>("id");
        prefix.originAs = node.get<std::string>("origin_as");
        prefix.prefix = node.get<std::string>("prefix");
        prefix.lanId = node.get<std::string>("lan_id");
        topology.originPrefixes.push_back(prefix);
    }

    return topology;
}

ScheduleConfig
LoadSchedule(const std::string& path)
{
    namespace pt = boost::property_tree;

    pt::ptree root;
    pt::read_json(path, root);

    ScheduleConfig schedule;
    uint32_t fileOrder = 0;

    if (auto events = root.get_child_optional("events"))
    {
        for (const auto& eventEntry : *events)
        {
            const pt::ptree& event = eventEntry.second;
            std::string type = event.get<std::string>("type", "");
            double time = event.get<double>("time", 0.0);
            schedule.lastEventTime = std::max(schedule.lastEventTime, time);

            if (type == "bgp_weight")
            {
                BgpWeightEvent weightEvent;
                weightEvent.id = event.get<std::string>("id");
                weightEvent.time = time;
                weightEvent.from = event.get<std::string>("from");
                weightEvent.to = event.get<std::string>("to");
                weightEvent.linkId = event.get<std::string>("link_id");
                weightEvent.weight = event.get<int32_t>("weight");
                weightEvent.active = event.get<bool>("active", weightEvent.weight > 0);
                weightEvent.label = event.get<std::string>("label", "");
                weightEvent.fileOrder = fileOrder;
                schedule.bgpWeightEvents.push_back(weightEvent);
            }

            ++fileOrder;
        }
    }

    std::stable_sort(schedule.bgpWeightEvents.begin(),
                     schedule.bgpWeightEvents.end(),
                     [](const BgpWeightEvent& lhs, const BgpWeightEvent& rhs) {
                         if (lhs.time != rhs.time)
                         {
                             return lhs.time < rhs.time;
                         }
                         return lhs.fileOrder < rhs.fileOrder;
                     });

    return schedule;
}

void
AssignAddress(Ptr<NetDevice> device, Ipv4Address address, Ipv4Mask mask)
{
    Ptr<Ipv4> ipv4 = device->GetNode()->GetObject<Ipv4>();
    int32_t interface = ipv4->GetInterfaceForDevice(device);
    if (interface == -1)
    {
        interface = ipv4->AddInterface(device);
    }
    ipv4->AddAddress(interface, Ipv4InterfaceAddress(address, mask));
    ipv4->SetMetric(interface, 1);
    ipv4->SetUp(interface);
}

void
ApplyDelay(const std::string& linkId, Ptr<CsmaChannel> channel, Time delay)
{
    channel->SetAttribute("Delay", TimeValue(delay));
    std::cout << "[ASPATH][DELAY] link=" << linkId
              << " delay_us=" << delay.GetMicroSeconds() << std::endl;
}

void
ScheduleDelayEvents(const std::string& schedulePath,
                    std::map<std::string, LinkRuntime>& links,
                    Time stopTime)
{
    namespace pt = boost::property_tree;

    pt::ptree root;
    pt::read_json(schedulePath, root);

    uint32_t count = 0;
    if (auto events = root.get_child_optional("events"))
    {
        for (const auto& eventEntry : *events)
        {
            const pt::ptree& event = eventEntry.second;
            if (event.get<std::string>("type", "") != "link_delay")
            {
                continue;
            }

            std::string id = event.get<std::string>("id");
            std::string linkId = event.get<std::string>("link_id");
            std::string mode = event.get<std::string>("mode");
            double time = event.get<double>("time");

            auto linkIt = links.find(linkId);
            if (linkIt == links.end())
            {
                throw std::runtime_error("link_delay event references unknown link: " + id);
            }

            if (mode == "static")
            {
                double delayMs = event.get<double>("delay_ms");
                Simulator::Schedule(Seconds(time),
                                    &ApplyDelay,
                                    linkId,
                                    linkIt->second.channel,
                                    Seconds(delayMs / 1000.0));
                ++count;
            }
            else if (mode == "linear")
            {
                double incrementMs = event.get<double>("increment_ms");
                double dt = event.get<double>("dt_s");
                if (dt <= 0.0)
                {
                    throw std::runtime_error("linear link_delay dt_s must be positive: " + id);
                }
                TimeValue currentDelayValue;
                linkIt->second.channel->GetAttribute("Delay", currentDelayValue);
                Time currentDelay = currentDelayValue.Get();
                uint32_t step = 0;
                for (double t = time; Seconds(t) <= stopTime; t += dt)
                {
                    Simulator::Schedule(Seconds(t),
                                        &ApplyDelay,
                                        linkId,
                                        linkIt->second.channel,
                                        currentDelay + Seconds((incrementMs * step) / 1000.0));
                    ++count;
                    ++step;
                }
            }
            else
            {
                throw std::runtime_error("Unsupported link_delay mode: " + mode);
            }
        }
    }

    std::cout << "[ASPATH][SCHEDULE] delay_events=" << count << std::endl;
}

void
ApplyBgpWeightEvent(std::shared_ptr<ScheduledBgpWeightAction> action)
{
    const BgpWeightEvent& event = action->event;
    action->localBgp->SetPeerPassive(action->peerAddress, !event.active);
    action->localBgp->SetPeerWeight(action->peerAddress, event.weight);

    std::cout << "[ASPATH][POLICY] time=" << Simulator::Now().GetSeconds()
              << " id=" << event.id
              << " type=bgp_weight"
              << " from=" << event.from
              << " to=" << event.to
              << " link=" << event.linkId
              << " weight=" << event.weight
              << " active=" << event.active
              << " reset_policy="
              << (action->forcePeerReset ? "force-peer-reset"
                                          : (action->allowPeerReset ? "allow-peer-reset" : "none"))
              << " source_context=scenario_policy"
              << " label=\"" << event.label << "\"" << std::endl;

    if (g_eventLogger)
    {
        g_eventLogger->LogEvent(Simulator::Now().GetSeconds(),
                                action->localRouterId,
                                action->localAsn,
                                "policy_change",
                                "",
                                Ipv4ToString(action->peerAddress),
                                "",
                                event.to,
                                "scenario_policy");
    }

    if (action->forcePeerReset)
    {
        action->localBgp->ResetPeer(action->peerAddress, !action->localPeerPassive && event.active);
        action->remoteBgp->ResetPeer(action->reversePeerAddress, !action->remotePeerPassive);
        std::cout << "[ASPATH][PEER_RESET] time=" << Simulator::Now().GetSeconds()
                  << " id=" << event.id
                  << " link=" << event.linkId
                  << " local=" << event.from
                  << " remote=" << event.to
                  << " reconnect_side="
                  << ((!action->localPeerPassive && event.active)
                          ? event.from
                          : ((!action->remotePeerPassive) ? event.to : "none"))
                  << " reason=force-peer-reset" << std::endl;
    }
    else if (action->allowPeerReset)
    {
        std::cout << "[ASPATH][PEER_RESET] time=" << Simulator::Now().GetSeconds()
                  << " id=" << event.id
                  << " action=not-used"
                  << " reason=allow-peer-reset-has-no-verified-fallback-condition-yet" << std::endl;
    }
}

} // namespace

int
main(int argc, char* argv[])
{
    std::string topologyPath;
    std::string schedulePath;
    std::string bgpTracePath;
    std::string outputDir;
    bool allowPeerReset = false;
    bool forcePeerReset = false;

    CommandLine cmd(__FILE__);
    cmd.AddValue("topologyPath", "Path to topology.json", topologyPath);
    cmd.AddValue("schedulePath", "Path to schedule.json", schedulePath);
    cmd.AddValue("bgpTracePath", "Path to bgp-events.csv", bgpTracePath);
    cmd.AddValue("outputDir", "Path to run output directory", outputDir);
    cmd.AddValue("allowPeerReset", "Allow peer reset fallback after weight updates", allowPeerReset);
    cmd.AddValue("forcePeerReset", "Force peer reset after weight updates", forcePeerReset);
    cmd.Parse(argc, argv);

    if (bgpTracePath.empty() && !outputDir.empty())
    {
        bgpTracePath = outputDir + "/bgp-events.csv";
    }
    if (bgpTracePath.empty())
    {
        throw std::runtime_error("bgpTracePath is required (or provide outputDir)");
    }

    SeedManager::SetSeed(12345);
    SeedManager::SetRun(1);
    std::cout << "[ASPATH][RNG] seed=12345 run=1" << std::endl;

    Topology topology = LoadTopology(topologyPath);
    ScheduleConfig schedule = LoadSchedule(schedulePath);
    Time stopTime = Seconds(std::max(60.0, schedule.lastEventTime + 60.0));

    NodeContainer routerNodes;
    routerNodes.Create(topology.ases.size());

    std::map<std::string, Ptr<Node>> routers;
    std::map<std::string, AsConfig> asById;
    std::map<std::string, uint32_t> asnByBgpRouterId;
    for (uint32_t i = 0; i < topology.ases.size(); ++i)
    {
        const AsConfig& as = topology.ases[i];
        routers[as.id] = routerNodes.Get(i);
        asById[as.id] = as;
        asnByBgpRouterId[as.bgpRouterId] = as.asn;
    }

    g_eventLogger = std::make_shared<EventCsvLogger>(bgpTracePath, asnByBgpRouterId);

    NodeContainer lanHosts;
    std::vector<LanRuntime> lans;
    for (const AsConfig& as : topology.ases)
    {
        for (const LanConfig& lan : as.lans)
        {
            LanRuntime runtime;
            runtime.asId = as.id;
            runtime.config = lan;
            runtime.host = CreateObject<Node>();
            lanHosts.Add(runtime.host);
            lans.push_back(runtime);
        }
    }

    InternetStackHelper internet;
    internet.Install(routerNodes);
    if (lanHosts.GetN() > 0)
    {
        internet.Install(lanHosts);
    }

    std::map<std::string, LinkRuntime> linkRuntimes;
    for (const LinkConfig& link : topology.links)
    {
        auto a = routers.find(link.asA);
        auto b = routers.find(link.asB);
        if (a == routers.end() || b == routers.end())
        {
            throw std::runtime_error("Link references unknown AS: " + link.id);
        }

        CsmaHelper csma;
        csma.SetChannelAttribute("DataRate", DataRateValue(DataRate(link.capacity)));
        csma.SetChannelAttribute("Delay", TimeValue(Time(link.delay)));

        NodeContainer endpoints(a->second, b->second);
        LinkRuntime runtime;
        runtime.config = link;
        runtime.devices = csma.Install(endpoints);
        runtime.channel = DynamicCast<CsmaChannel>(runtime.devices.Get(0)->GetChannel());
        runtime.subnet = SubnetForLink(link.asA, link.asB);
        runtime.addressA = AddressForLinkEndpoint(link.asA, link.asB);
        runtime.addressB = AddressForLinkEndpoint(link.asB, link.asA);
        runtime.asnA = asById.at(link.asA).asn;
        runtime.asnB = asById.at(link.asB).asn;
        runtime.aInitiates = runtime.asnA < runtime.asnB;

        AssignAddress(runtime.devices.Get(0), runtime.addressA, Ipv4Mask("255.255.255.252"));
        AssignAddress(runtime.devices.Get(1), runtime.addressB, Ipv4Mask("255.255.255.252"));
        runtime.interfaces.Add(a->second->GetObject<Ipv4>(), a->second->GetObject<Ipv4>()->GetInterfaceForAddress(runtime.addressA));
        runtime.interfaces.Add(b->second->GetObject<Ipv4>(), b->second->GetObject<Ipv4>()->GetInterfaceForAddress(runtime.addressB));

        linkRuntimes[link.id] = runtime;
    }

    uint32_t lanIndex = 0;
    std::map<std::string, Ipv4Address> lanRouterAddressById;
    for (LanRuntime& lan : lans)
    {
        CsmaHelper csma;
        csma.SetChannelAttribute("DataRate", DataRateValue(DataRate(lan.config.capacity)));
        csma.SetChannelAttribute("Delay", TimeValue(Time(lan.config.delay)));

        NodeContainer endpoints(routers.at(lan.asId), lan.host);
        lan.devices = csma.Install(endpoints);

        Ipv4Address routerAddress = LanAddress(lan.config.prefix, 1);
        Ipv4Address hostAddress = LanAddress(lan.config.prefix, 2);
        lanRouterAddressById[lan.config.id] = routerAddress;
        Ipv4Mask mask = MaskFromPrefix(lan.config.prefix);
        AssignAddress(lan.devices.Get(0), routerAddress, mask);
        AssignAddress(lan.devices.Get(1), hostAddress, mask);
        lan.interfaces.Add(routers.at(lan.asId)->GetObject<Ipv4>(),
                           routers.at(lan.asId)->GetObject<Ipv4>()->GetInterfaceForAddress(routerAddress));
        lan.interfaces.Add(lan.host->GetObject<Ipv4>(),
                           lan.host->GetObject<Ipv4>()->GetInterfaceForAddress(hostAddress));

        Ipv4StaticRoutingHelper staticRouting;
        Ptr<Ipv4StaticRouting> hostRoute = staticRouting.GetStaticRouting(lan.host->GetObject<Ipv4>());
        uint32_t hostIf = lan.host->GetObject<Ipv4>()->GetInterfaceForAddress(hostAddress);
        hostRoute->SetDefaultRoute(routerAddress, hostIf);

        ++lanIndex;
    }

    BgpRuntime bgpRuntime;
    for (const AsConfig& as : topology.ases)
    {
        Ptr<Bgp> bgp = CreateObject<Bgp>();
        bgp->SetAttribute("RouterID", Ipv4AddressValue(Ipv4Address(as.bgpRouterId.c_str())));
        bgp->SetAttribute("LibbgpLogLevel", EnumValue(libbgp::INFO));
        bgp->TraceConnectWithoutContext("RouteEvent", MakeCallback(&OnBgpRouteEvent));
        bgpRuntime.apps[as.id] = bgp;
    }

    for (const auto& entry : linkRuntimes)
    {
        const LinkRuntime& link = entry.second;

        Ptr<Bgp> bgpA = bgpRuntime.apps.at(link.config.asA);
        Ptr<Bgp> bgpB = bgpRuntime.apps.at(link.config.asB);

        Peer peerA;
        peerA.peer_address = link.addressB;
        peerA.peer_asn = link.asnB;
        peerA.local_asn = link.asnA;
        peerA.passive = !link.aInitiates;
        peerA.weight = link.config.initialBgpWeight;
        bgpA->AddPeer(peerA);

        Peer peerB;
        peerB.peer_address = link.addressA;
        peerB.peer_asn = link.asnA;
        peerB.local_asn = link.asnB;
        peerB.passive = link.aInitiates;
        peerB.weight = link.config.initialBgpWeight;
        bgpB->AddPeer(peerB);

        std::string keyA = DirectedPeerKey(link.config.asA, link.config.asB, link.config.id);
        std::string keyB = DirectedPeerKey(link.config.asB, link.config.asA, link.config.id);
        bgpRuntime.peerAddress[keyA] = link.addressB;
        bgpRuntime.peerAddress[keyB] = link.addressA;
        bgpRuntime.peerPassive[keyA] = peerA.passive;
        bgpRuntime.peerPassive[keyB] = peerB.passive;

        std::cout << "[ASPATH][BGP_PEER] link=" << link.config.id
                  << " from=" << link.config.asA
                  << " to=" << link.config.asB
                  << " local_asn=" << link.asnA
                  << " peer_asn=" << link.asnB
                  << " peer_address=" << link.addressB
                  << " passive=" << peerA.passive
                  << " initial_weight=" << peerA.weight << std::endl;
        std::cout << "[ASPATH][BGP_PEER] link=" << link.config.id
                  << " from=" << link.config.asB
                  << " to=" << link.config.asA
                  << " local_asn=" << link.asnB
                  << " peer_asn=" << link.asnA
                  << " peer_address=" << link.addressA
                  << " passive=" << peerB.passive
                  << " initial_weight=" << peerB.weight << std::endl;
    }

    for (const OriginPrefixConfig& prefix : topology.originPrefixes)
    {
        auto bgpIt = bgpRuntime.apps.find(prefix.originAs);
        if (bgpIt == bgpRuntime.apps.end())
        {
            throw std::runtime_error("Origin prefix references unknown AS: " + prefix.id);
        }
        auto lanIt = lanRouterAddressById.find(prefix.lanId);
        if (lanIt == lanRouterAddressById.end())
        {
            throw std::runtime_error("Origin prefix references unknown LAN: " + prefix.id);
        }

        bgpIt->second->AddRoute(Ipv4Address(NetworkAddressFromPrefix(prefix.prefix).c_str()),
                                Ipv4Mask(("/" + std::to_string(PrefixLengthFromPrefix(prefix.prefix))).c_str()),
                                lanIt->second);

        if (g_eventLogger)
        {
            const AsConfig& originAs = asById.at(prefix.originAs);
            g_eventLogger->LogEvent(0.0,
                                    originAs.bgpRouterId,
                                    originAs.asn,
                                    "originated_route",
                                    prefix.prefix,
                                    Ipv4ToString(lanIt->second),
                                    std::to_string(originAs.asn),
                                    "",
                                    "scenario_schedule");
        }

        std::cout << "[ASPATH][ORIGIN_ROUTE] id=" << prefix.id
                  << " origin_as=" << prefix.originAs
                  << " prefix=" << prefix.prefix
                  << " nexthop=" << lanIt->second << std::endl;
    }

    for (const AsConfig& as : topology.ases)
    {
        Ptr<Bgp> bgp = bgpRuntime.apps.at(as.id);
        routers.at(as.id)->AddApplication(bgp);
        bgp->SetStartTime(Seconds(0.0));
        std::cout << "[ASPATH][BGP_APP] as=" << as.id
                  << " asn=" << as.asn
                  << " router_id=" << as.bgpRouterId
                  << " start=0"
                  << " simulator_stop=" << stopTime.GetSeconds() << std::endl;
    }

    for (const BgpWeightEvent& event : schedule.bgpWeightEvents)
    {
        std::string key = DirectedPeerKey(event.from, event.to, event.linkId);
        std::string reverseKey = ReverseDirectedPeerKey(event);
        if (!bgpRuntime.apps.count(event.from) || !bgpRuntime.apps.count(event.to) ||
            !bgpRuntime.peerAddress.count(key) || !bgpRuntime.peerAddress.count(reverseKey))
        {
            throw std::runtime_error("bgp_weight event references unknown peer: " + event.id);
        }
        auto action = std::make_shared<ScheduledBgpWeightAction>();
        action->event = event;
        action->localBgp = bgpRuntime.apps.at(event.from);
        action->peerAddress = bgpRuntime.peerAddress.at(key);
        action->remoteBgp = bgpRuntime.apps.at(event.to);
        action->reversePeerAddress = bgpRuntime.peerAddress.at(reverseKey);
        action->localPeerPassive = bgpRuntime.peerPassive.at(key);
        action->remotePeerPassive = bgpRuntime.peerPassive.at(reverseKey);
        action->allowPeerReset = allowPeerReset;
        action->forcePeerReset = forcePeerReset;
        action->localRouterId = asById.at(event.from).bgpRouterId;
        action->localAsn = asById.at(event.from).asn;
        Simulator::Schedule(Seconds(event.time), &ApplyBgpWeightEvent, action);
    }

    std::cout << "[ASPATH][CONFIG] topologyPath=" << topologyPath << std::endl;
    std::cout << "[ASPATH][CONFIG] schedulePath=" << schedulePath << std::endl;
    std::cout << "[ASPATH][CONFIG] bgpTracePath=" << bgpTracePath << std::endl;
    std::cout << "[ASPATH][CONFIG] outputDir=" << outputDir << std::endl;
    std::cout << "[ASPATH][CONFIG] allowPeerReset=" << allowPeerReset << std::endl;
    std::cout << "[ASPATH][CONFIG] forcePeerReset=" << forcePeerReset << std::endl;
    std::cout << "[ASPATH][TOPOLOGY] as_count=" << topology.ases.size()
              << " router_count=" << routerNodes.GetN()
              << " inter_as_link_count=" << linkRuntimes.size()
              << " lan_count=" << lans.size()
              << " lan_host_count=" << lanHosts.GetN()
              << " origin_prefix_count=" << topology.originPrefixes.size() << std::endl;
    std::cout << "[ASPATH][SCHEDULE] bgp_weight_events=" << schedule.bgpWeightEvents.size()
              << " stop_time=" << stopTime.GetSeconds()
              << " reset_policy="
              << (forcePeerReset ? "force-peer-reset" : (allowPeerReset ? "allow-peer-reset" : "none"))
              << std::endl;

    for (const AsConfig& as : topology.ases)
    {
        std::cout << "[ASPATH][AS] id=" << as.id
                  << " asn=" << as.asn
                  << " router_id=" << as.routerId
                  << " bgp_router_id=" << as.bgpRouterId << std::endl;
    }

    for (const auto& entry : linkRuntimes)
    {
        const LinkRuntime& link = entry.second;
        std::cout << "[ASPATH][LINK] id=" << link.config.id
                  << " endpoints=" << link.config.asA << "," << link.config.asB
                  << " capacity=" << link.config.capacity
                  << " delay=" << link.config.delay
                  << " subnet=" << link.subnet << "/30"
                  << " addr_" << link.config.asA << "=" << link.addressA
                  << " addr_" << link.config.asB << "=" << link.addressB
                  << " weight=" << link.config.initialBgpWeight << std::endl;
    }

    for (const LanRuntime& lan : lans)
    {
        std::cout << "[ASPATH][LAN] id=" << lan.config.id
                  << " as=" << lan.asId
                  << " prefix=" << lan.config.prefix
                  << " capacity=" << lan.config.capacity
                  << " delay=" << lan.config.delay
                  << " router_addr=" << lan.interfaces.GetAddress(0)
                  << " host_addr=" << lan.interfaces.GetAddress(1) << std::endl;
    }

    for (const OriginPrefixConfig& prefix : topology.originPrefixes)
    {
        std::cout << "[ASPATH][ORIGIN] id=" << prefix.id
                  << " origin_as=" << prefix.originAs
                  << " prefix=" << prefix.prefix
                  << " lan_id=" << prefix.lanId
                  << " status=advertised" << std::endl;
    }

    ScheduleDelayEvents(schedulePath, linkRuntimes, stopTime);

    std::cout << "[ASPATH][OBSERVABILITY] source=bgp_route_event"
              << " captures=route_add,route_withdraw"
              << " missing=selected_path_change,peer_state,explicit_rib_in,rib_out,raw_update_arrival"
              << " csv=" << bgpTracePath << std::endl;

    Simulator::Stop(stopTime);
    Simulator::Run();

    if (g_eventLogger)
    {
        g_eventLogger->Flush();
    }

    std::cout << "[ASPATH][DONE] simulator_run_completed stop_time="
              << stopTime.GetSeconds()
              << " cleanup=skipped_due_current_bgp_teardown_limit" << std::endl;
    std::cout.flush();
    std::_Exit(0);
}
