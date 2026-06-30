#include "bgp-minimal-scenario.h"
#include "ns3/core-module.h"
#include "ns3/csma-module.h"
#include "ns3/internet-module.h"
#include "ns3/bgp.h"
#include "ns3/csma-channel.h"
#include "ns3helper-network.h"
#include <boost/property_tree/json_parser.hpp>
#include <boost/property_tree/ptree.hpp>
#include <limits>
#include <sstream>

namespace
{
const char*
StageToString (BgpMinimalState::EventStage stage)
{
  switch (stage)
    {
    case BgpMinimalState::EventStage::INIT:
      return "INIT";
    case BgpMinimalState::EventStage::SWITCHOVER_SCHEDULED:
      return "SWITCHOVER_SCHEDULED";
    case BgpMinimalState::EventStage::SWITCHED_TO_RED:
      return "SWITCHED_TO_RED";
    case BgpMinimalState::EventStage::PHYSICAL_MAIN_DOWN:
      return "PHYSICAL_MAIN_DOWN";
    case BgpMinimalState::EventStage::PHYSICAL_MAIN_UP:
      return "PHYSICAL_MAIN_UP";
    case BgpMinimalState::EventStage::SWITCHED_BACK_TO_MAIN:
      return "SWITCHED_BACK_TO_MAIN";
    }
  return "UNKNOWN_STAGE";
}

void
LogScenarioEvent (const char* domain, const std::string& detail)
{
  std::ostringstream oss;
  oss << "[EVENT][" << domain << "][t=" << ns3::Simulator::Now ().GetSeconds ()
      << "s] " << detail;
  NS_LOG_UNCOND (oss.str ());
}

ns3::Ipv4Address
ParseAddress (const std::string& address)
{
  const std::string::size_type slash = address.find ('/');
  return ns3::Ipv4Address ((slash == std::string::npos) ? address.c_str ()
                                                        : address.substr (0, slash).c_str ());
}
} // namespace

BgpMinimalScenario::BgpMinimalScenario ()
  : m_activeLinkIndex (0),
    m_hasLinkConfig (false)
{
  LinkConfig mainConfig;
  mainConfig.index = 0;
  mainConfig.name = "d12_main";
  mainConfig.d1Address = ns3::Ipv4Address ("10.250.0.4");
  mainConfig.d2Address = ns3::Ipv4Address ("10.250.0.5");
  mainConfig.initialBgpWeight = 100;
  mainConfig.schedule.push_back (
    LinkWindow{ns3::Seconds (0), ns3::Seconds (60), DelayProfile{}});
  mainConfig.schedule.push_back (
    LinkWindow{ns3::Seconds (1500), ns3::Seconds (3600), DelayProfile{}});
  mainConfig.bgpEvents.push_back (
    BgpPreferenceEvent{ns3::Seconds (45), 0, false});
  mainConfig.bgpEvents.push_back (
    BgpPreferenceEvent{ns3::Seconds (3000), 100, true});

  LinkConfig redConfig;
  redConfig.index = 1;
  redConfig.name = "d12_red";
  redConfig.d1Address = ns3::Ipv4Address ("10.250.0.6");
  redConfig.d2Address = ns3::Ipv4Address ("10.250.0.7");
  redConfig.initialBgpWeight = 0;
  redConfig.schedule.push_back (
    LinkWindow{ns3::Seconds (0), ns3::Seconds (3600), DelayProfile{}});
  redConfig.bgpEvents.push_back (
    BgpPreferenceEvent{ns3::Seconds (45), 100, true});
  redConfig.bgpEvents.push_back (
    BgpPreferenceEvent{ns3::Seconds (3000), 0, false});

  m_linkConfigs.push_back (mainConfig);
  m_linkConfigs.push_back (redConfig);
  m_linkPhysicalUp.assign (m_linkConfigs.size (), true);
  m_linkBgpActive.assign (m_linkConfigs.size (), false);
  m_linkBgpWeight.assign (m_linkConfigs.size (), 0);
  m_linkBgpActive[0] = true;
  m_linkBgpWeight[0] = mainConfig.initialBgpWeight;
  m_linkBgpWeight[1] = redConfig.initialBgpWeight;
}

void
BgpMinimalScenario::LoadLinkConfig (const std::string& path)
{
  namespace pt = boost::property_tree;
  pt::ptree root;
  pt::read_json (path, root);

  std::vector<LinkConfig> configs;

  for (const auto& linkNode : root.get_child ("links"))
    {
      const pt::ptree& linkTree = linkNode.second;
      const std::string id = linkTree.get<std::string> ("id");
      LinkConfig config;
      config.index = configs.size ();
      config.name = id;
      config.d1Address = ParseAddress (linkTree.get<std::string> ("addresses.d1"));
      config.d2Address = ParseAddress (linkTree.get<std::string> ("addresses.d2"));
      config.capacityBps = linkTree.get<uint64_t> ("capacity");
      config.initialBgpWeight = linkTree.get<int32_t> ("bgp.initial_weight", 0);

      for (const auto& windowNode : linkTree.get_child ("schedule"))
        {
          const pt::ptree& windowTree = windowNode.second;
          LinkWindow window;
          window.up = ns3::Seconds (windowTree.get<double> ("up"));
          window.down = ns3::Seconds (windowTree.get<double> ("down"));
          window.delay.startUs = windowTree.get<double> ("delay_us.start");
          window.delay.minUs = windowTree.get<double> ("delay_us.min");
          window.delay.endUs = windowTree.get<double> ("delay_us.end");
          NS_ABORT_MSG_IF (window.down <= window.up,
                           "Invalid link schedule for " << id << ": down must be after up");
          config.schedule.push_back (window);
        }
      NS_ABORT_MSG_IF (config.schedule.empty (),
                       "Invalid link schedule for " << id << ": expected at least one window");

      for (const auto& eventNode : linkTree.get_child ("bgp.preference_events"))
        {
          const pt::ptree& eventTree = eventNode.second;
          BgpPreferenceEvent event;
          event.time = ns3::Seconds (eventTree.get<double> ("time"));
          event.weight = eventTree.get<int32_t> ("weight");
          event.active = eventTree.get<bool> ("active");
          config.bgpEvents.push_back (event);
        }

      configs.push_back (config);
    }

  NS_ABORT_MSG_IF (configs.empty (), "Link config must define at least one d1-d2 link");

  m_linkConfigs = configs;
  m_linkPhysicalUp.assign (m_linkConfigs.size (), true);
  m_linkBgpActive.assign (m_linkConfigs.size (), false);
  m_linkBgpWeight.assign (m_linkConfigs.size (), 0);
  for (std::size_t i = 0; i < m_linkConfigs.size (); ++i)
    {
      m_linkBgpWeight[i] = m_linkConfigs[i].initialBgpWeight;
      m_linkBgpActive[i] = m_linkConfigs[i].initialBgpWeight > 0;
    }
  m_activeLinkIndex = SelectBestActiveLink ();
  m_hasLinkConfig = true;
}

void BgpMinimalScenario::BuildTopology ()
{
  m_state.nodes.Create (6);

  ns3::InternetStackHelper internet;
  internet.Install (m_state.nodes);

  ns3::CsmaHelper csma_lan;
  ns3::CsmaHelper csma_01;

  csma_01.SetChannelAttribute ("DataRate", ns3::StringValue ("10Gbps"));
  csma_01.SetChannelAttribute ("Delay", ns3::StringValue ("100us"));

  // Intra-domain (internal) links
  csma_lan.SetChannelAttribute("DataRate", ns3::StringValue ("1Gbps"));
  csma_lan.SetChannelAttribute("Delay", ns3::StringValue ("100us"));

  // Inter-domain links
  m_state.d01 = csma_01.Install(ns3::NodeContainer (m_state.nodes.Get(0), m_state.nodes.Get(1)));
  m_state.d12_links.clear ();
  m_state.d12_links.reserve (m_linkConfigs.size ());
  for (const LinkConfig& link : m_linkConfigs)
    {
      ns3::CsmaHelper csma_12;
      std::ostringstream dataRate;
      dataRate << link.capacityBps << "bps";
      csma_12.SetChannelAttribute ("DataRate", ns3::StringValue (dataRate.str ()));
      csma_12.SetChannelAttribute (
        "Delay", ns3::TimeValue (ns3::MicroSeconds (link.schedule.front ().delay.minUs)));
      m_state.d12_links.push_back (
        csma_12.Install(ns3::NodeContainer (m_state.nodes.Get(1), m_state.nodes.Get(2))));
    }

  // LANs
  m_state.d0lan = csma_lan.Install(ns3::NodeContainer (m_state.nodes.Get (0), m_state.nodes.Get (3)));
  m_state.d1lan = csma_lan.Install(ns3::NodeContainer (m_state.nodes.Get (1), m_state.nodes.Get (4)));
  m_state.d2lan = csma_lan.Install(ns3::NodeContainer (m_state.nodes.Get (2), m_state.nodes.Get (5)));
}

void BgpMinimalScenario::ConfigureAddressing ()
{
  m_state.if01 = ns3helper::AssignP2p31(m_state.d01, ns3::Ipv4Address ("10.250.0.2"), ns3::Ipv4Address ("10.250.0.3"));

  m_state.if12_links.clear ();
  m_state.if12_links.reserve (m_linkConfigs.size ());
  for (const LinkConfig& link : m_linkConfigs)
    {
      m_state.if12_links.push_back (
        ns3helper::AssignP2p31(GetLinkDevices (link.index), link.d1Address, link.d2Address));
    }

  // Assign LAN addresses
  ns3::Ipv4AddressHelper ipv4;
  ipv4.SetBase ("10.0.0.0", "255.255.255.0"); m_state.if0lan = ipv4.Assign (m_state.d0lan);
  ipv4.SetBase ("10.0.1.0", "255.255.255.0"); m_state.if1lan = ipv4.Assign (m_state.d1lan);
  ipv4.SetBase ("10.0.2.0", "255.255.255.0"); m_state.if2lan = ipv4.Assign (m_state.d2lan);

  for (const LinkConfig& link : m_linkConfigs)
    {
      SetPhysicalLinkState (link.index,
                            IsLinkAvailableAt (link, ns3::Seconds (0)),
                            ns3::MicroSeconds (link.schedule.front ().delay.minUs));
    }
}

void BgpMinimalScenario::ConfigureRouting ()
{
  m_state.host0_ipv4 = m_state.nodes.Get (3)->GetObject<ns3::Ipv4> ();
  m_state.host1_ipv4 = m_state.nodes.Get (4)->GetObject<ns3::Ipv4> ();
  m_state.host2_ipv4 = m_state.nodes.Get (5)->GetObject<ns3::Ipv4> ();

  ns3helper::SetHostDefaultRoute(m_state.host0_ipv4, m_state.if0lan.GetAddress (1), m_state.if0lan.GetAddress (0));
  ns3helper::SetHostDefaultRoute(m_state.host1_ipv4, m_state.if1lan.GetAddress (1), m_state.if1lan.GetAddress (0));
  ns3helper::SetHostDefaultRoute(m_state.host2_ipv4, m_state.if2lan.GetAddress (1), m_state.if2lan.GetAddress (0));
}

void BgpMinimalScenario::ConfigureBgp (ns3::Time stopTime)
{
  NS_ABORT_MSG_IF (m_state.if12_links.empty (), "No d1-d2 links configured for BGP");

  ns3::Ptr<ns3::Bgp> bgp0 = ns3::CreateObject<ns3::Bgp> ();
  bgp0->SetAttribute ("RouterID", ns3::Ipv4AddressValue (m_state.if01.GetAddress (0)));
  bgp0->SetAttribute ("LibbgpLogLevel", ns3::EnumValue (libbgp::INFO));
  bgp0->AddRoute (
    ns3::Ipv4Address ("10.0.0.0"), ns3::Ipv4Mask ("/24"), m_state.if0lan.GetAddress (0));

  ns3::Peer peer0;
  peer0.peer_address = m_state.if01.GetAddress (1);
  peer0.peer_asn = 65001;
  peer0.local_asn = 65000;
  peer0.passive = false;
  bgp0->AddPeer (peer0);

  m_state.nodes.Get (0)->AddApplication (bgp0);
  bgp0->SetStartTime (ns3::Seconds (0));
  bgp0->SetStopTime (stopTime);

  ns3::Ptr<ns3::Bgp> bgp1 = ns3::CreateObject<ns3::Bgp> ();
  bgp1->SetAttribute ("RouterID", ns3::Ipv4AddressValue (m_state.if01.GetAddress (1)));
  bgp1->SetAttribute ("LibbgpLogLevel", ns3::EnumValue (libbgp::INFO));
  bgp1->AddRoute (
    ns3::Ipv4Address ("10.0.1.0"), ns3::Ipv4Mask ("/24"), m_state.if1lan.GetAddress (0));

  ns3::Peer peer_in_ext;
  peer_in_ext.peer_address = m_state.if01.GetAddress (0);
  peer_in_ext.peer_asn = 65000;
  peer_in_ext.local_asn = 65001;
  peer_in_ext.passive = false;
  bgp1->AddPeer (peer_in_ext);

  for (const LinkConfig& link : m_linkConfigs)
    {
      ns3::Ipv4InterfaceContainer& iface = GetLinkInterfaces (link.index);
      ns3::Peer peer_12;
      peer_12.peer_address = iface.GetAddress (1);
      peer_12.peer_asn = 65002;
      peer_12.local_asn = 65001;
      peer_12.passive = link.initialBgpWeight <= 0;
      peer_12.weight = link.initialBgpWeight;
      bgp1->AddPeer (peer_12);
    }

  m_state.nodes.Get (1)->AddApplication (bgp1);
  m_state.bgp1 = bgp1;
  bgp1->SetStartTime (ns3::Seconds (0));
  bgp1->SetStopTime (stopTime);

  ns3::Ptr<ns3::Bgp> bgp2 = ns3::CreateObject<ns3::Bgp> ();
  bgp2->SetAttribute ("RouterID", ns3::Ipv4AddressValue (m_state.if12_links.front ().GetAddress (1)));
  bgp2->SetAttribute ("LibbgpLogLevel", ns3::EnumValue (libbgp::INFO));
  bgp2->AddRoute (
    ns3::Ipv4Address ("10.0.2.0"), ns3::Ipv4Mask ("/24"), m_state.if2lan.GetAddress (0));

  for (const LinkConfig& link : m_linkConfigs)
    {
      ns3::Ipv4InterfaceContainer& iface = GetLinkInterfaces (link.index);
      ns3::Peer peer2;
      peer2.peer_address = iface.GetAddress (0);
      peer2.peer_asn = 65001;
      peer2.local_asn = 65002;
      peer2.passive = true;
      peer2.weight = link.initialBgpWeight;
      bgp2->AddPeer (peer2);
    }

  m_state.nodes.Get (2)->AddApplication (bgp2);
  m_state.bgp2 = bgp2;
  bgp2->SetStartTime (ns3::Seconds (0));
  bgp2->SetStopTime (stopTime);
}

const BgpMinimalScenario::LinkConfig&
BgpMinimalScenario::GetLinkConfig (std::size_t linkIndex) const
{
  NS_ABORT_MSG_IF (linkIndex >= m_linkConfigs.size (), "Invalid link index " << linkIndex);
  return m_linkConfigs[linkIndex];
}

BgpMinimalScenario::LinkConfig&
BgpMinimalScenario::GetLinkConfig (std::size_t linkIndex)
{
  NS_ABORT_MSG_IF (linkIndex >= m_linkConfigs.size (), "Invalid link index " << linkIndex);
  return m_linkConfigs[linkIndex];
}

std::string
BgpMinimalScenario::GetLinkName (std::size_t linkIndex) const
{
  return GetLinkConfig (linkIndex).name;
}

ns3::NetDeviceContainer&
BgpMinimalScenario::GetLinkDevices (std::size_t linkIndex)
{
  NS_ABORT_MSG_IF (linkIndex >= m_state.d12_links.size (), "Invalid link device index " << linkIndex);
  return m_state.d12_links[linkIndex];
}

ns3::Ipv4InterfaceContainer&
BgpMinimalScenario::GetLinkInterfaces (std::size_t linkIndex)
{
  NS_ABORT_MSG_IF (linkIndex >= m_state.if12_links.size (), "Invalid link interface index " << linkIndex);
  return m_state.if12_links[linkIndex];
}

bool
BgpMinimalScenario::IsLinkAvailableAt (const LinkConfig& link, ns3::Time time) const
{
  for (const LinkWindow& window : link.schedule)
    {
      if ((time >= window.up) && (time < window.down))
        {
          return true;
        }
    }
  return false;
}

void
BgpMinimalScenario::ConfigureLinkDelay (std::size_t linkIndex, ns3::Time delay)
{
  ns3::Ptr<ns3::Channel> channel = GetLinkDevices (linkIndex).Get (0)->GetChannel ();
  ns3::Ptr<ns3::CsmaChannel> csmaChannel = ns3::DynamicCast<ns3::CsmaChannel> (channel);
  NS_ABORT_MSG_IF (csmaChannel == nullptr, "Expected CsmaChannel for " << GetLinkName (linkIndex));
  csmaChannel->SetAttribute ("Delay", ns3::TimeValue (delay));
}

std::size_t
BgpMinimalScenario::SelectBestActiveLink () const
{
  std::size_t best = 0;
  int32_t bestWeight = std::numeric_limits<int32_t>::min ();
  bool found = false;

  for (std::size_t i = 0; i < m_linkConfigs.size (); ++i)
    {
      if (!m_linkPhysicalUp[i] || !m_linkBgpActive[i] || m_linkBgpWeight[i] <= 0)
        {
          continue;
        }
      if (!found || m_linkBgpWeight[i] > bestWeight)
        {
          best = i;
          bestWeight = m_linkBgpWeight[i];
          found = true;
        }
    }

  if (found)
    {
      return best;
    }
  if (m_activeLinkIndex < m_linkConfigs.size ())
    {
      return m_activeLinkIndex;
    }
  return 0;
}

void
BgpMinimalScenario::RefreshActiveBgpPeer (std::size_t triggerLinkIndex)
{
  if (m_state.bgp1 == nullptr || m_state.bgp2 == nullptr || m_linkConfigs.empty ())
    {
      return;
    }

  const std::size_t selectedLinkIndex = SelectBestActiveLink ();
  if (selectedLinkIndex >= m_linkConfigs.size () || !m_linkPhysicalUp[selectedLinkIndex] ||
      !m_linkBgpActive[selectedLinkIndex] || m_linkBgpWeight[selectedLinkIndex] <= 0)
    {
      return;
    }

  ns3::Ipv4InterfaceContainer& iface = GetLinkInterfaces (selectedLinkIndex);
  m_state.bgp2->ResetPeer (iface.GetAddress (0), false);
  m_state.bgp1->ResetPeer (iface.GetAddress (1), true);

  std::ostringstream oss;
  oss << "RefreshActiveBgpPeer selected=" << GetLinkName (selectedLinkIndex)
      << " trigger=" << GetLinkName (triggerLinkIndex);
  LogScenarioEvent ("SYSTEM", oss.str ());
}

void
BgpMinimalScenario::SetPhysicalLinkState (std::size_t linkIndex, bool up, ns3::Time delay)
{
  ConfigureLinkDelay (linkIndex, delay);

  if (up)
    {
      ns3helper::bringUpLink (m_state.nodes, GetLinkInterfaces (linkIndex), 1u, 2u);
    }
  else
    {
      ns3helper::bringDownLink (m_state.nodes, GetLinkInterfaces (linkIndex), 1u, 2u);
    }

  m_linkPhysicalUp[linkIndex] = up;
  m_activeLinkIndex = SelectBestActiveLink ();
  m_state.stage = up ? BgpMinimalState::EventStage::PHYSICAL_MAIN_UP
                     : BgpMinimalState::EventStage::PHYSICAL_MAIN_DOWN;

  if (m_state.bgp1 != nullptr && m_state.bgp2 != nullptr)
    {
      ns3::Ipv4InterfaceContainer& iface = GetLinkInterfaces (linkIndex);
      m_state.bgp2->ResetPeer (iface.GetAddress (0), false);
      m_state.bgp1->ResetPeer (iface.GetAddress (1), up && m_linkBgpActive[linkIndex]);
    }
  if (!up)
    {
      RefreshActiveBgpPeer (linkIndex);
    }

  std::ostringstream oss;
  oss << "SetPhysicalLinkState " << GetLinkName (linkIndex)
      << (up ? " up" : " down")
      << " delay_us=" << delay.GetMicroSeconds ()
      << " active_link=" << GetActiveLinkName ();
  LogScenarioEvent ("SCENARIO", oss.str ());
}

void
BgpMinimalScenario::ApplyBgpPreference (std::size_t linkIndex, int32_t weight, bool active)
{
  ns3::Ipv4InterfaceContainer& iface = GetLinkInterfaces (linkIndex);

  NS_ABORT_MSG_IF (m_state.bgp1 == nullptr || m_state.bgp2 == nullptr,
                   "BGP preference change requested before BGP is configured");

  m_linkBgpActive[linkIndex] = active;
  m_linkBgpWeight[linkIndex] = weight;

  m_state.bgp1->SetPeerPassive (iface.GetAddress (1), !active);
  m_state.bgp2->SetPeerPassive (iface.GetAddress (0), true);
  m_state.bgp1->SetPeerWeight (iface.GetAddress (1), weight);
  m_state.bgp2->SetPeerWeight (iface.GetAddress (0), weight);

  m_state.bgp2->ResetPeer (iface.GetAddress (0), false);
  m_state.bgp1->ResetPeer (iface.GetAddress (1), active && m_linkPhysicalUp[linkIndex]);

  m_activeLinkIndex = SelectBestActiveLink ();
  if (!active || weight <= 0)
    {
      RefreshActiveBgpPeer (linkIndex);
    }
  m_state.stage = active ? BgpMinimalState::EventStage::SWITCHED_TO_RED
                         : BgpMinimalState::EventStage::SWITCHOVER_SCHEDULED;

  std::ostringstream oss;
  oss << "BGP preference " << GetLinkName (linkIndex)
      << " weight=" << weight
      << " active=" << (active ? "true" : "false")
      << " selected=" << GetActiveLinkName ()
      << " stage=" << StageToString (m_state.stage);
  LogScenarioEvent ("SYSTEM", oss.str ());
}

void
BgpMinimalScenario::ScheduleConfiguredEvents (ns3::Time stopTime)
{
  for (const LinkConfig& link : m_linkConfigs)
    {
      for (const LinkWindow& window : link.schedule)
        {
          const ns3::Time delay = ns3::MicroSeconds (window.delay.minUs);
          if (window.up > ns3::Seconds (0) && window.up < stopTime)
            {
              ns3::Simulator::Schedule (window.up,
                                        &BgpMinimalScenario::SetPhysicalLinkState,
                                        this,
                                        link.index,
                                        true,
                                        delay);
            }
          if (window.down < stopTime)
            {
              ns3::Simulator::Schedule (window.down,
                                        &BgpMinimalScenario::SetPhysicalLinkState,
                                        this,
                                        link.index,
                                        false,
                                        delay);
            }
        }

      for (const BgpPreferenceEvent& event : link.bgpEvents)
        {
          if (event.time < stopTime)
            {
              ns3::Simulator::Schedule (event.time,
                                        &BgpMinimalScenario::ApplyBgpPreference,
                                        this,
                                        link.index,
                                        event.weight,
                                        event.active);
            }
        }
    }

  std::ostringstream oss;
  oss << "ScheduleConfiguredEvents for " << m_linkConfigs.size ()
      << " links through " << stopTime.GetSeconds () << "s";
  LogScenarioEvent ("SCHEDULER", oss.str ());
}

ns3::Ptr<ns3::Node> BgpMinimalScenario::GetPingSourceNode () const
{
  return m_state.nodes.Get (3);
}

ns3::Ipv4Address BgpMinimalScenario::GetPingDestinationAddress () const
{
  return m_state.if2lan.GetAddress (1);
}

std::string
BgpMinimalScenario::GetActiveLinkName () const
{
  if (m_linkConfigs.empty ())
    {
      return "none";
    }
  return GetLinkName (SelectBestActiveLink ());
}
