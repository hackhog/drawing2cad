// Read an AP242 file with the independent STEPcode schema library.
// This adapter does not evaluate EXPRESS WHERE rules or geometric correctness.
#include "cleditor/STEPfile.h"
#include "clstepcore/Registry.h"
#include "clstepcore/STEPattribute.h"
#include "clstepcore/STEPcomplex.h"
#include "clstepcore/ExpDict.h"
#include "clstepcore/sdai.h"
#include "clutils/errordesc.h"
#include <algorithm>
#include <cctype>
#include <iostream>
#include <map>
#include <set>
#include <sstream>
#include <string>
#include <vector>

extern void SchemaInit(Registry &);

static const char *revision = "24783b448511b8f6bce2829286a3f00015430236";
static const char *schema_hash = "32ced62e799a50cc857966ab6702adcbc5b0da00be290f232dcea275652059cf";
static const char *schema_name = "AP242_MANAGED_MODEL_BASED_3D_ENGINEERING_MIM_LF";

static std::string quote(const std::string &value) {
    std::ostringstream output;
    output << '"';
    const char *hex = "0123456789abcdef";
    for (unsigned char character : value) {
        if (character == '"' || character == '\\') output << '\\' << character;
        else if (character < 0x20)
            output << "\\u00" << hex[character >> 4] << hex[character & 15];
        else output << character;
    }
    output << '"';
    return output.str();
}

static std::string upper(std::string value) {
    std::transform(value.begin(), value.end(), value.begin(),
                   [](unsigned char c) { return std::toupper(c); });
    return value;
}

static bool schema_matches(STEPfile &file, std::string &actual) {
    InstMgr *headers = file.HeaderInstances();
    for (int index = 0; index < headers->InstanceCount(); ++index) {
        auto *instance = headers->GetApplication_instance(index);
        if (!instance || upper(instance->EntityName()) != "FILE_SCHEMA") continue;
        instance->ResetAttributes();
        auto *attribute = instance->NextAttribute();
        if (!attribute) return false;
        actual = upper(attribute->asStr());
        // Require one schema. Retain the ASN.1 identifier without certification.
        const std::string start = "('" + std::string(schema_name);
        if (actual.compare(0, start.size(), start) != 0) return false;
        const auto end = actual.find('\'', start.size());
        if (end == std::string::npos || actual.substr(end) != "')") return false;
        return actual.size() > start.size() &&
               (actual[start.size()] == '\'' || actual[start.size()] == ' ');
    }
    return false;
}

int main(int argc, char **argv) {
    // Arguments are fixed by the maintained restricted-worker adapter.
    if (argc != 4) return 64;
    std::streambuf *stdout_buffer = std::cout.rdbuf(std::cerr.rdbuf());
    Registry registry(SchemaInit);
    InstMgr instances;
    STEPfile file(registry, instances, "", true);
    file.ReadExchangeFile(argv[1]);
    const int read_severity = file.Error().severity();
    std::string actual_schema;
    const bool matches = schema_matches(file, actual_schema);
    ErrorDescriptor verification;
    int verify_severity = SEVERITY_NULL;
    if (read_severity >= SEVERITY_USERMSG && matches)
        verify_severity = instances.VerifyInstances(verification);
    const bool accepted = read_severity >= SEVERITY_USERMSG &&
                          verify_severity >= SEVERITY_USERMSG && matches &&
                          instances.InstanceCount() > 0;
    std::map<std::string, int> counts;
    std::ostringstream inventory;
    bool first = true;
    const std::set<std::string> selected = {
        "DIMENSIONAL_SIZE", "DIMENSIONAL_LOCATION", "DIMENSIONAL_CHARACTERISTIC_REPRESENTATION",
        "SHAPE_DIMENSION_REPRESENTATION", "GEOMETRIC_ITEM_SPECIFIC_USAGE",
        "DRAUGHTING_MODEL_ITEM_ASSOCIATION", "TESSELLATED_ANNOTATION_OCCURRENCE",
        "SHAPE_ASPECT", "SHAPE_ASPECT_RELATIONSHIP", "LENGTH_MEASURE_WITH_UNIT",
        "MEASURE_REPRESENTATION_ITEM", "SI_UNIT", "LENGTH_UNIT",
        "ADVANCED_FACE", "CLOSED_SHELL", "MANIFOLD_SOLID_BREP", "ADVANCED_BREP_SHAPE_REPRESENTATION",
        "SHAPE_DEFINITION_REPRESENTATION", "PRODUCT_DEFINITION_SHAPE", "PRODUCT_DEFINITION",
        "PRODUCT_DEFINITION_FORMATION", "PRODUCT", "DESCRIPTIVE_REPRESENTATION_ITEM",
        "GLOBAL_UNIT_ASSIGNED_CONTEXT", "DRAUGHTING_MODEL"
    };
    size_t inventory_size = 0;
    bool inventory_complete = true;
    if (accepted) for (int index = 0; index < instances.InstanceCount(); ++index) {
        auto *instance = instances.GetApplication_instance(index);
        if (!instance) continue;
        const std::string type = upper(instance->EntityName());
        std::vector<SDAI_Application_instance *> components;
        if (instance->IsComplex()) {
            for (auto *component = static_cast<STEPcomplex *>(instance); component; component = component->sc)
                components.push_back(component);
        } else components.push_back(instance);
        bool include = false;
        for (auto *component : components) {
            const std::string name = upper(component->EntityName());
            ++counts[name];
            include = include || selected.count(name);
        }
        if (!include) continue;
        if (type == "DESCRIPTIVE_REPRESENTATION_ITEM") {
            bool dimension_identifier = false;
            instance->ResetAttributes();
            while (auto *attribute = instance->NextAttribute()) {
                if (std::string(attribute->Name()) == "name" &&
                    attribute->asStr() == "'drawing2cad dimension id'") dimension_identifier = true;
            }
            if (!dimension_identifier) continue;
        }
        std::ostringstream row;
        row << "{\"id\":" << instance->STEPfile_id << ",\"type\":" << quote(type) << ",\"types\":[";
        bool first_type = true;
        for (auto *component : components) {
            if (!first_type) row << ',';
            first_type = false;
            row << quote(upper(component->EntityName()));
        }
        row << "],\"attributes\":[";
        bool first_attribute = true;
        for (auto *component : components) {
            component->ResetAttributes();
            while (auto *attribute = component->NextAttribute()) {
                if (!first_attribute) row << ',';
                first_attribute = false;
                row << "{\"name\":" << quote(attribute->Name())
                    << ",\"value\":" << quote(attribute->asStr()) << '}';
            }
        }
        row << "]}";
        if (inventory_size + row.str().size() > 96000) { inventory_complete = false; continue; }
        inventory_size += row.str().size();
        if (!first) inventory << ',';
        first = false;
        inventory << row.str();
    }
    std::cout.rdbuf(stdout_buffer);
    std::cout << "\nD2C_RESULT:{\"status\":" << quote(accepted ? "pass" : "fail")
              << ",\"analyzer\":\"STEPcode\",\"adapter_profile\":\"drawing2cad.stepcode/1\""
              << ",\"source_revision\":" << quote(revision)
              << ",\"schema_sha256\":" << quote(schema_hash)
              << ",\"actual_schema\":" << quote(actual_schema)
              << ",\"input_sha256\":" << quote(argv[3])
              << ",\"sandbox\":" << argv[2]
              << ",\"entity_count\":" << instances.InstanceCount()
              << ",\"read_severity\":" << read_severity
              << ",\"verify_severity\":" << verify_severity
              << ",\"diagnostics\":" << quote((file.Error().UserMsg() + file.Error().DetailMsg() +
                                                  verification.UserMsg() + verification.DetailMsg()).substr(0, 4000))
              << ",\"checks\":[{\"check\":\"independent_ap242_schema_read\",\"status\":" << quote(accepted ? "pass" : "fail")
              << "},{\"check\":\"full_express_validation\",\"status\":\"not_tested\"}"
              << ",{\"check\":\"exact_edition_conformance\",\"status\":\"not_tested\"}"
              << ",{\"check\":\"independent_geometry_correctness\",\"status\":\"not_tested\"}"
              << ",{\"check\":\"independent_pmi_semantics\",\"status\":\"not_tested\"}]"
              << ",\"pmi_inventory_complete\":" << (inventory_complete ? "true" : "false")
              << ",\"pmi_inventory\":[" << inventory.str() << "],\"entity_counts\":{";
    first = true;
    for (const auto &count : counts) {
        if (!first) std::cout << ',';
        first = false;
        std::cout << quote(count.first) << ':' << count.second;
    }
    std::cout << "}}\n";
    return 0;
}
